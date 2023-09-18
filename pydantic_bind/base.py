from enum import Enum, EnumType
from functools import cache
from importlib import import_module
from pydantic import BaseModel as PydanticBaseModel, ConfigDict, computed_field
from pydantic.fields import ComputedFieldInfo, FieldInfo
from pydantic.json_schema import GenerateJsonSchema
from pydantic._internal._decorators import Decorator
from pydantic._internal._internal_dataclass import slots_dataclass
from pydantic._internal._model_construction import ModelMetaclass, PydanticGenericMetadata
from pydantic_core import PydanticUndefined
import sys
from typing import Any, Dict, List, Type, Union, cast


@cache
def get_pybind_type(typ: Union[Enum, ModelMetaclass]) -> Union[EnumType, Type]:
    """
    Return the generated pybind type corresponding to the BaseNodel-derived type

    :param typ: A Pydantic BaseModel-derived type
    :return: The corresponding, generated pybind type
    """

    module_parts = typ.__module__.split(".")
    module_parts.insert(-1, "__pybind__")
    pybind_module = ".".join(module_parts)

    module = sys.modules.get(pybind_module)
    if not module:
        module = import_module(pybind_module)

    return getattr(module, typ.__name__)


@slots_dataclass
class PropertyFieldInfo(ComputedFieldInfo):
    default: Any = PydanticUndefined

    @property
    def required(self) -> bool:
        return self.default is PydanticUndefined

    @classmethod
    def from_computed_field_info(cls, info: ComputedFieldInfo, default=PydanticUndefined):
        kwargs = {s: getattr(info, s) for s in info.__slots__}
        kwargs["default"] = default
        return PropertyFieldInfo(**kwargs)

    @classmethod
    def from_field_info(cls, info: FieldInfo, wrapped_property: property):
        kwargs = {s: getattr(info, s) for s in set(info.__slots__).intersection(ComputedFieldInfo.__slots__)}
        kwargs["wrapped_property"] = wrapped_property
        kwargs["default"] = info.default
        kwargs["return_type"] = info.annotation
        return PropertyFieldInfo(**kwargs)


def to_title(snake_str: str) -> str:
    return " ".join(word.title() for word in snake_str.split("_"))


def _getter(name: str, typ: Union[EnumType, Type]):
    def fn(self):
        ret = getattr(self.pybind_impl, name)
        if issubclass(typ, Enum):
            ret = typ[ret.name]

        return ret

    fn.__name__ = name
    fn.__annotations__ = {"return": typ}

    return fn


def _setter(name: str, typ: Union[EnumType, Type]):
    def fn(self, value: Any):
        if issubclass(typ, Enum):
            value = get_pybind_type(typ)[value.name]

        setattr(self.pybind_impl, name, value)

    fn.__name__ = name
    fn.__annotations__ = {"value": typ}

    return fn


class ModelMetaclassNoCopy(ModelMetaclass):
    def __new__(
        mcs,
        cls_name: str,
        bases: tuple[type[Any], ...],
        namespace: dict[str, Any],
        __pydantic_generic_metadata__: PydanticGenericMetadata | None = None,
        __pydantic_reset_parent_namespace__: bool = True,
        **kwargs: Any,
    ) -> type:
        annotations = namespace.get("__annotations__", {})

        if annotations:
            # Rewrite annotations as properties, with getters and setters which interact with the attributes
            # on the generated pybind_impl class

            properties = {}

            for name, typ in annotations.items():
                value = namespace.get(name, PydanticUndefined)
                field = computed_field(property(fget=_getter(name, typ), fset=_setter(name, typ)))
                if isinstance(value, FieldInfo):
                    field.decorator_info = PropertyFieldInfo.from_field_info(value,
                                                                             field.decorator_info.wrapped_property)
                else:
                    field.decorator_info = PropertyFieldInfo.from_computed_field_info(field.decorator_info, value)

                field.decorator_info.title = to_title(name)
                properties[name] = field

            for name, prop in properties.items():
                annotations.pop(name)
                namespace[name] = prop

            # ToDo: add signature

        ret = cast(ModelMetaclass, super().__new__(mcs, cls_name, bases, namespace, **kwargs))
        ret.__pydantic_decorators__.__annotations__["computed_fields"] = dict[str, Decorator[PropertyFieldInfo]]

        return ret


def json_schema_extra(schema: Dict[str, Any], model_class: ModelMetaclassNoCopy) -> None:
    generator = GenerateJsonSchema(by_alias=True)
    definitions: List[Dict] = model_class.__pydantic_core_schema__["definitions"]
    definition = next(d for d in definitions if d["cls"] == model_class)
    computed_schema = definition["schema"]["computed_fields"]
    schema.pop("additionalProperties", None)
    properties = schema["properties"]
    required = schema.setdefault("required", [])

    for field in computed_schema:
        property_name = field["property_name"]
        alias = field["alias"]
        field_schema = generator.computed_field_schema(field)
        property_info = model_class.__pydantic_decorators__.computed_fields[property_name].info

        if property_info.default == PydanticUndefined:
            required.append(alias)
        else:
            field_schema["default"] = property_info.default

        field_schema["title"] = property_info.title
        properties[alias] = field_schema


class BaseModel(PydanticBaseModel):

    def model_post_init(self, __context: Any):
        self.__pybind_impl = get_pybind_type(
            type(self))(**{name: getattr(self, name) for name in self.model_fields.keys()})\
            if self.model_config.get("frozen") else None

    @property
    def pybind_impl(self):
        return self.__pybind_impl or\
            get_pybind_type(type(self))(**{name: getattr(self, name) for name in self.model_fields.keys()})


class BaseModelNoCopy(PydanticBaseModel, metaclass=ModelMetaclassNoCopy):
    model_config = ConfigDict(json_schema_extra=json_schema_extra)

    @property
    def model_computed_fields(self) -> dict[str, PropertyFieldInfo]:
        return cast(dict[str, PropertyFieldInfo], super().model_computed_fields)

    @property
    def pybind_impl(self):
        return self.__pybind_impl

    def __init__(self, **kwargs):
        missing_required = []

        for name, field_info in self.model_computed_fields.items():
            value = kwargs.get(name, PydanticUndefined)
            if value == PydanticUndefined:
                if field_info.alias:
                    value = kwargs.get(field_info.alias, PydanticUndefined)
                    if issubclass(field_info.return_type, Enum):
                        value = get_pybind_type(field_info.return_type)[value.name]

                if value == PydanticUndefined:
                    if field_info.required:
                        missing_required.append(name)
                else:
                    kwargs.pop(name)
                    kwargs[field_info.alias] = value

            elif issubclass(field_info.return_type, Enum):
                kwargs[name] = get_pybind_type(field_info.return_type)[value.name]

        if missing_required:
            raise RuntimeError(f"Missing required fields: {missing_required}")

        super().__init__()

        pybind_type = get_pybind_type(type(self))
        self.__pybind_impl = pybind_type(**kwargs)

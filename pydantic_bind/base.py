from dataclasses import dataclass as orig_dataclass, is_dataclass
from enum import Enum, EnumType
from functools import cache, wraps
from importlib import import_module
from pydantic import BaseModel as BaseModel, ConfigDict, computed_field
from pydantic.fields import ComputedFieldInfo, FieldInfo
from pydantic.json_schema import GenerateJsonSchema
from pydantic._internal._config import ConfigWrapper
from pydantic._internal._decorators import Decorator
from pydantic._internal._internal_dataclass import slots_dataclass
from pydantic._internal._model_construction import ModelMetaclass, PydanticGenericMetadata, generate_model_signature
from pydantic._internal._utils import ClassAttribute
from pydantic_core import PydanticUndefined
import sys
from types import UnionType
from typing import Any, Dict, List, Type, Optional, Union, cast, get_args, get_origin


class UnconvertableValue(Exception):
    pass


class __IBaseModelNoCopy:
    pass


def field_info_iter(model_class: ModelMetaclass):
    if is_dataclass(model_class):
        for field_name, field in model_class.__dataclass_fields__.items():
            yield field_name, field.type, field.default
    elif issubclass(model_class, BaseModelNoCopy):
        for field_name, field in model_class.__pydantic_decorators__.computed_fields.items():
            yield field_name, field.info.return_type, field.info.default
    else:
        for field_name, field in model_class.model_fields.items():
            yield field_name, field.annotation, field.default


@cache
def get_pybind_type(typ: Union[Enum, ModelMetaclass]) -> Union[EnumType, Type]:
    """
    Return the generated pybind type corresponding to the BaseNodel-derived type

    :param typ: A dataclass or Pydantic BaseModel-derived type
    :return: The corresponding, generated pybind type
    """

    module_parts = typ.__module__.split(".")
    module_parts.insert(-1, "__pybind__")
    pybind_module = ".".join(module_parts)

    module = sys.modules.get(pybind_module)
    if not module:
        module = import_module(pybind_module)

    return getattr(module, typ.__name__)


def get_pybind_value(obj):
    """
    Return the generated pybind type corresponding to the BaseNodel-derived type

    :param obj: A dataclass or Pydantic BaseModel-derived object
    :return: The corresponding pybind object
    """
    return _get_pybind_value(obj, False)


def _get_pybind_value(obj, default_to_self: bool = True):
    if isinstance(obj, Enum):
        return get_pybind_type(type(obj)).__entries[obj.name][0]
    elif is_dataclass(obj):
        return get_pybind_type(type(obj))(**{name: _get_pybind_value(getattr(obj, name))
                                             for name in obj.__dataclass_fields__.keys()})
    elif isinstance(obj, __IBaseModelNoCopy):
        return get_pybind_type(type(obj))(**{name: _get_pybind_value(getattr(obj, name))
                                             for name in obj.model_computed_fields.keys()})
    elif isinstance(obj, BaseModel):
        return get_pybind_type(type(obj))(**{name: _get_pybind_value(getattr(obj, name))
                                             for name in obj.model_fields.keys()})
    elif default_to_self:
        return obj
    else:
        raise UnconvertableValue("Only dataclasses and pydantic classes supported")


def from_pybind_value(value, typ: Type):
    origin = get_origin(typ)
    args = get_args(typ)
    is_dc = is_dataclass(typ)

    if origin is Optional:
        typ = args[0]
    elif origin in (Union, UnionType):
        typ = next(a for a in args if a.__name__ == type(value).__name__)

    if issubclass(typ, Enum):
        return typ[value.name]
    elif issubclass(typ, __IBaseModelNoCopy) or (is_dc and hasattr(typ, "__no_copy__")):
        return typ(__pybind_impl__=value)
    elif is_dc or issubclass(typ, BaseModel):
        # This is quite inefficient
        kwargs = {}
        for field_name, field_type, _ in field_info_iter(typ):
            kwargs[field_name] = from_pybind_value(getattr(value, field_name), field_type)
        return typ(**kwargs)
    else:
        return value


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
        return from_pybind_value(getattr(self.pybind_impl, name), typ)

    fn.__name__ = name
    fn.__annotations__ = {"return": typ}

    return fn


def _setter(name: str, typ: Union[EnumType, Type]):
    def fn(self, value: Any):
        setattr(self.pybind_impl, name, _get_pybind_value(value))

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
        config_wrapper = ConfigWrapper.for_model(bases, namespace, kwargs)
        annotations = namespace.get("__annotations__", {})
        field_infos = {}

        if annotations:
            # Rewrite annotations as properties, with getters and setters which interact with the attributes
            # on the generated pybind_impl class

            properties = {}

            for name, typ in annotations.items():
                value = namespace.get(name, PydanticUndefined)
                field = computed_field(property(fget=_getter(name, typ), fset=_setter(name, typ)))
                if isinstance(value, FieldInfo):
                    field_infos[name] = value
                    field.decorator_info = PropertyFieldInfo.from_field_info(value,
                                                                             field.decorator_info.wrapped_property)
                else:
                    field.decorator_info = PropertyFieldInfo.from_computed_field_info(field.decorator_info, value)
                    field_infos[name] = FieldInfo(annotation=typ, default=value)

                field.decorator_info.title = to_title(name)
                properties[name] = field

            for name, prop in properties.items():
                annotations.pop(name)
                namespace[name] = prop

        cls = cast(ModelMetaclass, super().__new__(mcs, cls_name, bases, namespace, **kwargs))
        cls.__pydantic_decorators__.__annotations__["computed_fields"] = dict[str, Decorator[PropertyFieldInfo]]
        cls.__signature__ = ClassAttribute(
            '__signature__', generate_model_signature(cls.__init__, field_infos, config_wrapper)
        )

        return cls


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


class BaseModelNoCopy(BaseModel, __IBaseModelNoCopy, metaclass=ModelMetaclassNoCopy):
    model_config = ConfigDict(json_schema_extra=json_schema_extra)

    @property
    def model_computed_fields(self) -> dict[str, PropertyFieldInfo]:
        return cast(dict[str, PropertyFieldInfo], super().model_computed_fields)

    @property
    def pybind_impl(self):
        return self.__pybind_impl

    def __init__(self, **kwargs):
        super().__init__()

        __pybind_impl__ = kwargs.pop("__pybind_impl__", None)
        if __pybind_impl__:
            self.__pybind_impl = __pybind_impl__
        else:
            missing_required = []

            for name, field_info in self.model_computed_fields.items():
                value = kwargs.get(name, PydanticUndefined)
                if value == PydanticUndefined:
                    if field_info.alias:
                        value = kwargs.get(field_info.alias, PydanticUndefined)

                    if value == PydanticUndefined:
                        if field_info.required:
                            missing_required.append(name)
                    else:
                        kwargs.pop(name)
                        kwargs[field_info.alias] = value

                if value != PydanticUndefined:
                    kwargs[name] = _get_pybind_value(value)

            if missing_required:
                raise RuntimeError(f"Missing required fields: {missing_required}")

            pybind_type = get_pybind_type(type(self))
            self.__pybind_impl = pybind_type(**kwargs)


def __dc_init(init):
    @wraps(init)
    def wrapper(self, *args, __pybind_impl__=None, **kwargs):
        self.__pybind_impl = __pybind_impl__ or get_pybind_type(type(self))()
        return init(self, *args, **kwargs)

    return wrapper


def dataclass(cls=None, /, *, init=True, repr=True, eq=True, order=False,
              unsafe_hash=False, frozen=False, match_args=True,
              kw_only=False, slots=False, weakref_slot=False):

    ret = orig_dataclass(cls, init=init, repr=repr, eq=eq, order=order, unsafe_hash=unsafe_hash, frozen=frozen,
                         match_args=match_args, kw_only=kw_only, slots=slots, weakref_slot=weakref_slot)

    for name, field in ret.__dataclass_fields__.items():
        setattr(cls, name, property(fget=_getter(name, field.type), fset=_setter(name, field.type)))

    ret.__init__ = __dc_init(ret.__init__)
    ret.__no_copy__ = True

    return ret

from enum import Enum, EnumType
from functools import cache
from importlib import import_module
from itertools import chain

import sys
from typing import Any, Union


@cache
def get_pybind_type(typ: Union[Enum, type]) -> Union[EnumType, type]:
    """
    Return the generated pybind type corresponding to the BaseNodel-derived type

    :param typ: A dataclass or Pydantic BaseModel-derived type
    :return: The corresponding, generated pybind type
    """

    package_parts = typ.__module__.split(".")
    pybind_module_name = "_".join(package_parts)
    pybind_module = ".".join(chain(package_parts[:-1], ["__pybind__", pybind_module_name]))

    module = sys.modules.get(pybind_module)
    if not module:
        module = import_module(pybind_module)

    return getattr(module, typ.__name__)


def from_pybind_value(value: Any, _typ: type) -> Any:
    if isinstance(value, Enum):
        return get_pybind_type(type(value)).__entries[value.name][0]

    return value


def to_pybind_value(value: Any, _typ: type) -> Any:
    if isinstance(value, Enum):
        return value.name

    return value


class PybindRedirectMixin:
    @classmethod
    def __pybind_type(cls) -> type:
        return get_pybind_type(cls)

    def __redirect_get_value__(self, field: str, typ: type) -> Any:
        value = getattr(self._pybind_instance, field)
        return from_pybind_value(value, typ)

    def __redirect_set_value__(self, field: str, value: Any, typ: type):
        try:
            pybind_instance = self._pybind_instance
        except AttributeError:
            pybind_instance = self._pybind_instance = self.__pybind_type()()

        setattr(pybind_instance, field, to_pybind_value(value, typ))

    def __redirect_set_model_values__(self, values: dict[str, tuple[Any, type]]):
        kwargs = {k: to_pybind_value(v, t) for k, (v, t) in values.items()}
        self._pybind_instance = self.__pybind_type()(**kwargs)

    # def from_msg_pack(self, data):
    #     return self.__pybind_type().from_msg_pack(data)

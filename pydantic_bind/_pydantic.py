from abc import ABC
from functools import cache
from pydantic import BaseModel
from pydantic._internal._model_construction import ModelMetaclass
from pydantic_core import PydanticUndefined

from ._descriptors import FieldDescriptor
from ._pybind import PybindRedirectMixin
from ._redirect import Redirector
from ._redirect_meta import RedirectMeta


class PydanticFieldDescriptor(FieldDescriptor, property):
    """
    Yuck. This is because the only descriptor that pydantic recognises and will call __set__ on is a property.
    See https://github.com/pydantic/pydantic/blob/d5f4bde014f12e0b2d03d46d77925d808053ff16/pydantic/main.py#L949
    """
    pass


class RedirectModelMetaclass(RedirectMeta, ModelMetaclass):
    _MISSING = PydanticUndefined
    _FIELD_DESCRIPTOR = PydanticFieldDescriptor


class RedirectBaseModel(Redirector, BaseModel, ABC, metaclass=RedirectModelMetaclass):
    @classmethod
    @cache
    def redirect_model_fields(cls: type[BaseModel]) -> set[str]:
        return set(cls.__pydantic_fields__.keys())


class PybindBaseModel(PybindRedirectMixin, RedirectBaseModel):
    pass

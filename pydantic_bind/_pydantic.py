from abc import ABC
from functools import cache
from pydantic import BaseModel
from pydantic._internal._model_construction import ModelMetaclass
from pydantic_core import PydanticUndefined
from typing import Any

from ._pybind import PybindRedirectMixin
from ._redirect import Redirector
from ._redirect_meta import RedirectMeta


class PydanticExtraDescriptor:
    def __get__(self, instance: BaseModel, owner: type[BaseModel]):
        if instance:
            ret = {f: getattr(instance, f) for f in instance.model_fields}
            try:
                ret.update(object.__getattribute__(instance, "__pydantic_extra_orig__"))
            except AttributeError:
                pass

            return ret

        return self

    def __set__(self, instance: BaseModel, value: dict[str, Any]):
        if value:
            object.__setattr__(instance, "__pydantic_extra_orig__", value)


class RedirectModelMetaclass(RedirectMeta, ModelMetaclass):
    _MISSING = PydanticUndefined

    def __new__(cls, cls_name: str, bases: tuple[type[Any], ...], namespace: dict[str, Any], **kwargs):
        # pydantic_core grabs __dict__ inside rust and accesses it directly to get values for model_dump()/
        # model_dump_json(). I suppose it's a bit quicker than calling getattr for each of the model fields,
        # but it's super annoying. The only way we can get serialisation to work (without changing pydantic_core)
        # is to return our fields via __pydantic_extra__.
        #
        # Hijack __pydantic_extra__ with our own descriptor, which will return the model fields plus anything
        # passed as extra

        _extra = namespace.pop("__pydantic_extra__", None)
        # TODO add a warning here

        namespace["__pydantic_extra__"] = PydanticExtraDescriptor()
        ret = super().__new__(cls, cls_name, bases, namespace, **kwargs)

        for f in ret.model_fields.values():
            f.repr = False

        return ret


class RedirectBaseModel(Redirector, BaseModel, ABC, metaclass=RedirectModelMetaclass):
    @classmethod
    @cache
    def redirect_model_fields(cls: type[BaseModel]) -> set[str]:
        return set(cls.__pydantic_fields__.keys())


class PybindBaseModel(PybindRedirectMixin, RedirectBaseModel):
    pass

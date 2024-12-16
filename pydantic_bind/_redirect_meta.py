from dataclasses import MISSING
from typing import Any

from ._descriptors import DictDescriptor, FieldDescriptor


class RedirectMeta:
    _MISSING = MISSING

    def __new__(cls, cls_name: str, bases: tuple[type[Any], ...], namespace: dict[str, Any], **kwargs):
        namespace["__dict__"] = DictDescriptor()

        descriptors = {}
        for name, typ in namespace.get("__annotations__", {}).items():
            value = namespace.get(name, cls._MISSING)
            if value is cls._MISSING or not hasattr(value, "__get__"):
                descriptors[name] = FieldDescriptor(name, value, typ)

        ret = super().__new__(cls, cls_name, bases, namespace, **kwargs)
        for name, descriptor in descriptors.items():
            setattr(ret, name, descriptor)

        return ret

from _ctypes import Py_DECREF, Py_INCREF
from ctypes import POINTER, pythonapi, py_object
from typing import Any

from ._redirect import RedirectDict, Redirector


class FieldDescriptor:
    def __init__(self, name: str, default: Any, typ: type):
        self.__default = default
        self.__name = name
        self.__type = typ

    def __get__(self, instance: Redirector, owner: type[Redirector]) -> Any:
        if instance is not None:
            return instance.__redirect_get_value__(self.__name, self.__type)

        return self.__default

    def __set__(self, instance: Redirector, value: Any):
        instance.__redirect_set_value__(self.__name, value, self.__type)

    @property
    def type(self) -> type:
        return self.__type


class DictDescriptor:
    __obj_dict_ptr = None

    @classmethod
    def __dict_ptr(cls):
        if cls.__obj_dict_ptr is None:
            dict_ptr = pythonapi._PyObject_GetDictPtr
            dict_ptr.argtypes = (py_object,)
            dict_ptr.restype = POINTER(py_object)
            cls.__obj_dict_ptr = dict_ptr

        return cls.__obj_dict_ptr

    def __set_dict(self, instance: Redirector, value: dict[str, Any]) -> dict:
        dict_ = RedirectDict(instance)
        dict_contents = self.__dict_ptr()(instance).contents
        prev = dict_contents.value if dict_contents else None
        Py_INCREF(dict_)
        dict_contents.value = dict_

        if prev is not None:
            Py_DECREF(prev)

        if value:
            cls = type(instance)
            values = {k: (v, type(v)) for k, v in value.items()}
            # values = {k: (v, object.__getattribute__(cls, k).type) for k, v in value.items()}
            instance.__redirect_set_values__(values)

        return dict_

    def __get__(self, instance: Redirector, owner: type[Redirector]) -> dict[str, Any]:
        contents = self.__dict_ptr()(instance).contents
        if not contents.value:
            return self.__set_dict(instance, {})

        if type(contents.value) is dict:
            return self.__set_dict(instance, contents.value)

        return contents.value

    def __set__(self, instance: Redirector, value: dict[str, Any]):
        self.__set_dict(instance, value)

from abc import abstractmethod
from typing import Any


class Redirector:
    @classmethod
    @abstractmethod
    def redirect_model_fields(cls) -> set[str]:
        ...

    @abstractmethod
    def __redirect_get_value__(self, field: str, typ: type) -> Any:
        ...

    @abstractmethod
    def __redirect_set_value__(self, key: str, value: Any, typ: type):
        ...

    def __redirect_set_values__(self, items: dict[str, tuple[Any, type]]):
        # Override this if you want to e.g. return a new object, constructed from all model values
        for field, (value, typ) in items.items():
            self.__redirect_set_value__(field, value, typ)


class RedirectDict(dict):
    def __init__(self, owner: Redirector):
        super().__init__()
        self.__owner = owner  # Should this be a weakref ?

    def __iter__(self):
        return self.__owner.redirect_model_fields().__iter__()

    def __contains__(self, item):
        return item in self.__owner.redirect_model_fields() or super().__contains__(item)

    def __getitem__(self, item):
        owner = self.__owner
        if item in owner.redirect_model_fields():
            return owner.__redirect_get_value__(item, None)
            # return owner.__redirect_get_value__(item, object.__getattribute__(type(owner), item).type)
        return super().__getitem__(item)

    def __setitem__(self, key, value):
        owner = self.__owner
        if key in owner.redirect_model_fields():
            owner.__redirect_set_value__(key, value, type(value))
            # owner.__redirect_set_value__(key, value, object.__getattribute__(type(owner), key).type)
        else:
            super().__setitem__(key, value)

    def __len__(self):
        return len(self.__owner.redirect_model_fields())

    def __repr__(self):
        return self.__model_fields_dict.__repr__()

    def update(self, seq=None, **kwargs):
        if seq:
            if hasattr(seq, "keys"):
                for k in seq:
                    self.__setitem__(k, seq[k])
            else:
                for k, v in seq:
                    self.__setitem__(k, v)

        for k, v in kwargs.items():
            self.__setitem__(k, v)

    def keys(self):
        return self.__owner.redirect_model_fields()

    def values(self):
        owner = self.__owner
        return [owner.__redirect_get_value__(k, None) for k in self.keys()]

    def items(self):
        return zip(self.keys(), self.values())

    @property
    def __model_fields_dict(self) -> dict[str, Any]:
        return dict(self.items())

    @property
    def _debug_dict(self) -> dict[str, Any]:
        return {**self.__model_fields_dict, **dict(super().items())}

    @property
    def _debug_parent_dict(self) -> dict[str, Any]:
        return dict(super().items())

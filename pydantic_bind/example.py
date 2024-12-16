from dataclasses import dataclass
from functools import cached_property
from pydantic import BaseModel
from typing import Any

from pydantic_bind import RedirectBaseModel, RedirectDataclass


class DictRedirectMixin:
    """ Trivial example implementation """
    @cached_property
    def __dict(self) -> dict[str, Any]:
        return {}

    def __redirect_get_value__(self, field: str, _typ: type) -> Any:
        return self.__dict.get(field)

    def __redirect_set_value__(self, field: str, value: Any, _typ: type):
        self.__dict[field] = value


# This should not need to derive from BaseMode, as RedirectBaseModel already does.
# However, if you leave it out, PyCharm introspection breaks. Ugh
class Foo(DictRedirectMixin, RedirectBaseModel, BaseModel):
    s: str
    i: int
    o: str | None = None


@dataclass
class Baz(DictRedirectMixin, RedirectDataclass):
    s: str
    i: int
    o: str | None = None


f = Foo(s="Nick", i=666)
b = Baz(s="Nick", i=666)

print(f"i: {f.i} {type(f.__dict__)} {f.__dict__}")
print(repr(f))
print(f"i: {b.i} {type(b.__dict__)} {b.__dict__._debug_parent_dict}")
print()

from abc import ABC, ABCMeta
from dataclasses import dataclass, fields
from functools import cache

from ._pybind import PybindRedirectMixin
from ._redirect import Redirector
from ._redirect_meta import RedirectMeta


class RedirectAbstractMeta(RedirectMeta, ABCMeta):
    pass


@dataclass
class RedirectDataclass(Redirector, ABC, metaclass=RedirectAbstractMeta):
    @classmethod
    @cache
    def redirect_model_fields(cls) -> set[str]:
        return set(fld.name for fld in fields(cls))


@dataclass
class PybindDataclass(PybindRedirectMixin, RedirectDataclass):
    pass

from .base import BaseModel, dataclass, get_pybind_type, get_pybind_value

import os

if os.environ.get('PYDANTIC_BIND_DISABLE', False) == "True":
    # If you wish to disable pydantic_bind behaviour and default to native pydantic and dataclass implementations,
    # set PYDANTIC_BIND_DISABLE=True
    from pydantic import BaseModel
    from dataclasses import dataclass


__all__ = (
    BaseModel,
    dataclass,
    get_pybind_type,
    get_pybind_value
)

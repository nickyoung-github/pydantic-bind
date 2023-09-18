from argparse import ArgumentParser
from collections.abc import Mapping, Sequence
from dataclasses import MISSING, is_dataclass
import datetime as dt
from enum import Enum, EnumType
from importlib import import_module
from inspect import isclass
from pathlib import Path
from pydantic import BaseModel
from pydantic._internal._model_construction import ModelMetaclass
from pydantic_core import PydanticUndefined
from textwrap import indent
from types import UnionType
from typing import Any, Optional, Set, Tuple, Union, get_origin, get_args

from pydantic_bind.base import BaseModelNoCopy

__base_type_mappings = {
    bool: ("boolean", None),
    float: ("double", None),
    int: ("int", None),
    str: ("std::string", "<string>"),
    dt.date: ("std::chrono::system_clock::time_point", "<chrono>"),
    dt.datetime: ("std::chrono::system_clock::time_point", "<chrono>"),
    dt.time: ("std::chrono::system_clock::time_point", "<chrono>"),
    dt.timedelta: ("std::chrono::duration", "<chrono>")
}

__no_move_types = {
    bool, float, int, dt.date, dt.datetime, dt.time, dt.timedelta
}

NoneT = type(None)


def cpp_default(value: Any) -> str | None:
    if value in (MISSING, PydanticUndefined):
        return None
    elif value is None:
        return "std::nullopt"
    elif isinstance(value, bool):
        return "true" if value else "false"
    elif isinstance(value, str):
        return f'"{value}"'
    elif isinstance(value, Enum):
        return value.name
    elif isinstance(value, (int, float)):
        return str(value)
    elif isinstance(value, (list, set, tuple)):
        return f'{{{", ".join(cpp_default(v) for v in value)}}}'
    elif isinstance(value, dict):
        items_str = (f"{{{cpp_default(k)}, {cpp_default(v)}}}" for k, v in value.items())
        return f'{{ {", ".join(items_str)} }}'
    else:
        raise RuntimeError(f"Unsupported default value {value}")


def cpp_type(typ) -> Tuple[str, Set[str]]:
    def args_type(base_type: str) -> Tuple[str, Set[str]]:
        optional = False
        real_args = ()

        for arg in args:
            if arg is NoneT:
                optional = True
            else:
                real_args += (arg,)

        arg_types = ()
        all_arg_includes = {f"<{base_type.replace('std::', '')}>"}
        if optional:
            all_arg_includes.add("<optional>")

        for arg in real_args:
            arg_type, arg_includes = cpp_type(arg)
            arg_types += (arg_type,)
            all_arg_includes.update(arg_includes)

        args_cpp_type = arg_types[0] if len(arg_types) == 1 else f"{base_type}<{', '.join(arg_types)}>"

        return f"std::optional<{args_cpp_type}>" if optional else args_cpp_type, all_arg_includes

    dot = r'.'
    slash = r'/'
    base_cpp_type, include = __base_type_mappings.get(typ, (None, None))
    if base_cpp_type:
        return base_cpp_type, {include} if include else {}
    else:
        origin = get_origin(typ)
        args = get_args(typ)

        if origin is None:
            if typ in (dict, list, set, tuple):
                if args:
                    origin = typ
                else:
                    raise RuntimeError(f"Cannot use non parameterised collection {typ} as a type")
            elif issubclass(typ, BaseModel) or is_dataclass(typ) or issubclass(typ, Enum):
                return typ.__name__, {f'"{typ.__module__.replace(dot, slash)}.h"'}
            else:
                raise RuntimeError(f"Can only use builtins, datetime or BaseModel-derived types, not {typ}")

        if origin is Optional:
            cpp_typ, includes = cpp_type(args[0])
            return f"std::optional<{cpp_typ}>", includes.union(("optional",))
        elif origin in (Union, UnionType):
            return args_type("std::variant")
        elif origin in (list, Sequence):
            cpp_typ, includes = cpp_type(args[0])
            return f"std::vector<{cpp_typ}>", includes.union(("vector",))
        elif origin is set:
            cpp_typ, includes = cpp_type(args[0])
            return f"std::set<{cpp_typ}>", includes.union(("set",))
        elif origin is tuple:
            if Ellipsis in args:
                if len(args) != 2 or args[1] is not Ellipsis:
                    raise RuntimeError("Cannot support Ellipsis/Any as a tuple parameter type")

                # We've got something like Tuple[int, ...], treat it as a vector
                cpp_typ, includes = cpp_type(args[0])
                return f"std::vector<{cpp_typ}>", includes.union(("vector",))
            else:
                # An actual tuple
                return args_type("std::tuple")
        elif origin in (dict, Mapping):
            key_type, key_includes = cpp_type(args[0])
            value_type, value_includes = cpp_type(args[0])
            return f"std::unordered_map<{key_type}, {value_type}>", \
                key_includes.union(value_includes).union("unordered_map", )
        else:
            raise RuntimeError(f"Cannot handle type {typ}")


def generate_enum(enum_typ: EnumType):
    items = (f"{i.name} = {i.value}" for i in enum_typ)
    return f"""enum {enum_typ.__name__} {{ {', '.join(items)} }};"""


def generate_class(model_class: ModelMetaclass) -> Tuple[Optional[str], Optional[str], Optional[Tuple[str, ...]]]:
    def field_info_iter():
        if is_dataclass(model_class):
            for field_name, field in model_class.__dataclass_fields__.items():
                yield field_name, field.type, field.default
        elif issubclass(model_class, BaseModelNoCopy):
            for field_name, field in model_class.__pydantic_decorators__.computed_fields.items():
                yield field_name, field.info.return_type, field.info.default
        else:
            for field_name, field in model_class.model_fields.items():
                yield field_name, field.annotation, field.default

    frozen = model_class.__dataclass_params__.frozen if is_dataclass(model_class) else \
        model_class.model_config.get("frozen")
    types = []
    kwargs = []
    constructor_args = []
    init_args = []
    struct_members = []
    pydantic_attrs = []
    names = []
    all_includes = {"<msgpack/msgpack.h>"}
    pydantic_def = ".def_readonly" if frozen else ".def_readwrite"
    cls_name = model_class.__name__
    newline = "\n    "

    for name, field_type, default in field_info_iter():
        names.append(name)
        typ, includes = cpp_type(field_type)
        all_includes.update(includes)
        default = cpp_default(default)
        default_suffix = f'={default}' if default else ""
        move = field_type not in __no_move_types
        position = len(types) if default else 0  # Need to ensure non-defaulted params are first

        constructor_args.insert(position, f"{typ} {name + default_suffix}")
        init_args.insert(position, f"{name}({name if not move else f'std::move({name})'})")
        kwargs.insert(position, f'py::arg("{name}")' + default_suffix)
        types.insert(position, typ)
        struct_members.insert(position, f"{typ} {name};")
        pydantic_attrs.insert(position, f'{pydantic_def}("{name}", &{cls_name}::{name})')

    if not types:
        return None, None, None

    # ToDo: wrap lines

    struct_def = f"""struct {cls_name}
{{
    {cls_name}({', '.join(constructor_args)}) :
        {', '.join(init_args)}
    {{
    }}

    {newline.join(struct_members)}
    
    template<class T>
    void msgpack(T &pack)
    {{
        pack({', '.join(names)});
    }}
}};"""

    pydantic_def = f"""py::class_<{cls_name}>(m, "{cls_name}")
    .def(py::init<{', '.join(types)}>(), {', '.join(kwargs)})
    {newline.join(pydantic_attrs)};"""

    return struct_def, pydantic_def, tuple(f"#include {i}" for i in sorted(all_includes))


def generate_module(module_name: str, output_dir: str):
    single_newline = "\n"
    double_newline = "\n\n"
    dot = r'.'
    slash = r'/'

    module = import_module(module_name)
    generated_root = Path(output_dir)
    self_include = f'#include "{module_name.replace(dot, slash)}.h"'
    module_base_name = module.__name__.split('.')[-1]
    namespace = module.__name__.split('.')[0]
    guard = f"{namespace.upper()}_{module_base_name.upper()}_H"

    if not generated_root.exists():
        generated_root.mkdir(parents=True, exist_ok=True)

    includes = set()
    struct_defs = []
    pydantic_defs = []
    enum_defs = []

    for clz in (v for v in vars(module).values() if isclass(v)):
        if clz is not Enum and issubclass(clz, Enum):
            enum_defs.append(generate_enum(clz))
        elif is_dataclass(clz) or issubclass(clz, BaseModel):
            struct, pydantic, struct_includes = generate_class(clz)
            if struct:
                struct_defs.append(struct)
                pydantic_defs.append(pydantic)
                includes = includes.union(struct_includes)

                if self_include in includes:
                    includes.remove(self_include)

    header_contents = f"""
#ifndef {guard}
#define {guard}

{single_newline.join(includes)}

namespace {namespace}
{{

{double_newline.join(indent(enum_def, ' ' * 4) for enum_def in enum_defs)}

{double_newline.join(indent(struct_def, ' ' * 4) for struct_def in struct_defs)}

}} // {namespace}

#endif // {guard}
"""

    cpp_contents = f"""
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "{module_base_name}.h"

namespace py = pybind11;
using namespace {namespace};


PYBIND11_MODULE({module_base_name}, m)
{{
{double_newline.join(indent(pydantic_def, ' ' * 4) for pydantic_def in pydantic_defs)}
}}
"""

    with Path(output_dir, f"{module_base_name}.h").open("w") as header_file:
        header_file.write(header_contents)

    with Path(output_dir, f"{module_base_name}.cpp").open("w") as cpp_file:
        cpp_file.write(cpp_contents)


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("-m", "--module", type=str, required=True)
    parser.add_argument("-o", "--output_dir", type=str, required=True)
    cl_args = parser.parse_args()

    generate_module(cl_args.module, cl_args.output_dir)

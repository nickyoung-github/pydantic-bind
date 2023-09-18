from argparse import ArgumentParser
from collections.abc import Mapping, Sequence
import datetime as dt
from importlib import import_module
from inspect import isclass
from pathlib import Path
from pydantic import BaseModel
from pydantic._internal._model_construction import ModelMetaclass
from pydantic_core import PydanticUndefined
from textwrap import indent
from types import UnionType
from typing import Any, Optional, Set, Tuple, Union, get_origin, get_args

from pydantic_bind.base import BaseModelNoCopy, ModelMetaclassNoCopy


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
    if value is PydanticUndefined:
        return None
    elif value is None:
        return "std::nullopt"
    elif isinstance(value, bool):
        return "true" if value else "false"
    elif isinstance(value, str):
        return f'"{value}"'
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
            elif issubclass(typ, BaseModelNoCopy):
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
            return f"std::vector<{cpp_typ}>", includes.union(("optional",))
        elif origin is set:
            cpp_typ, includes = cpp_type(args[0])
            return f"std::set<{cpp_typ}>", includes.union(("optional",))
        elif origin is tuple:
            if Ellipsis in args:
                if len(args) != 2 or args[1] is not Ellipsis:
                    raise RuntimeError("Cannot support Ellipsis/Any as a tuple parameter type")

                # We've got something like Tuple[int, ...], treat it as a vector
                cpp_typ, includes = cpp_type(args[0])
                return f"std::vector<{cpp_typ}>", includes.union(("optional",))
            else:
                # An actual tuple
                return args_type("std::tuple")
        elif origin in (dict, Mapping):
            key_type, key_includes = cpp_type(args[0])
            value_type, value_includes = cpp_type(args[0])
            return f"std::unordered_map<{key_type}, {value_type}>", key_includes.union(value_includes)
        else:
            raise RuntimeError(f"Cannot handle type {typ}")


def generate_class(model_class: ModelMetaclass):
    def field_info_iter():
        if issubclass(model_class, ModelMetaclassNoCopy):
            for field_name, field in model_class._pydantic_decorators__.computed_fields.items():
                yield field_name, field.return_type, field.default
        else:
            for field_name, field in model_class.model_fields.items():
                yield field_name, field.type, field.default

    types = []
    kwargs = []
    constructor_args = []
    init_args = []
    struct_members = []
    pydantic_attrs = []
    all_includes = set()
    pydantic_def = ".def_read" if model_class.model_config.get("frozen") else ".def_readwrite"
    cls_name = model_class.__name__
    newline = "\n    "

    for name, field_type, default in field_info_iter():
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

    # ToDo: wrap lines

    struct_def = f"""struct {cls_name}
{{
    {cls_name}({', '.join(constructor_args)}) :
        {', '.join(init_args)}
    {{
    }}
    
    {newline.join(struct_members)}
}};"""

    pydantic_def = f"""py::class_<{cls_name}>(m, "{cls_name}")
    .def(py::init<{', '.join(types)}>(), {', '.join(kwargs)})
    {newline.join(pydantic_attrs)};"""

    return struct_def, pydantic_def, tuple(f"#include {i}" for i in sorted(all_includes))


def generate_module(module_name: str, output_dir: str):
    newline = "\n\n"
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

    for model_class in (v for v in vars(module).values() if isclass(v) and issubclass(v, BaseModel)):
        if model_class.__pydantic_decorators__.computed_fields:
            struct, pydantic, struct_includes = generate_class(model_class)
            struct_defs.append(struct)
            pydantic_defs.append(pydantic)
            includes = includes.union(struct_includes)

    if self_include in includes:
        includes.remove(self_include)

    header_contents = f"""
#ifndef {guard}
#define {guard}

{newline.join(includes)}

namespace {namespace}
{{

{newline.join(indent(struct, ' ' * 4) for struct in struct_defs)}

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
{newline.join(indent(pydantic, ' ' * 4) for pydantic in pydantic_defs)}
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

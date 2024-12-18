from argparse import ArgumentParser
from collections.abc import Mapping, Sequence
from dataclasses import MISSING, is_dataclass, fields
import datetime as dt
from enum import Enum, EnumType
from itertools import chain
from importlib import import_module
from inspect import isclass
from pathlib import Path
from pydantic_core import PydanticUndefined
from textwrap import TextWrapper
from types import UnionType
from typing import Any, Optional, Set, Tuple, Union, get_args, get_origin

from ._dataclasses import PybindDataclass
from ._pydantic import PybindBaseModel

__base_type_mappings = {
    bool: ("bool", None),
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


def field_info_iter(typ: type[PybindBaseModel] | type[PybindDataclass]):
    if issubclass(typ, PybindBaseModel):
        for field_name, field in typ.model_fields.items():
            yield field_name, field.annotation, field.default
    elif issubclass(typ, PybindDataclass):
        for fld in fields(typ):
            yield fld.name, fld.type, fld.default


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
        return f"{type(value).__name__}::{value.name}"
    elif isinstance(value, (int, float)):
        return str(value)
    elif isinstance(value, (list, set, tuple)):
        return f'{{{", ".join(cpp_default(v) for v in value)}}}'
    elif isinstance(value, dict):
        items_str = (f"{{{cpp_default(k)}, {cpp_default(v)}}}" for k, v in value.items())
        return f'{{ {", ".join(items_str)} }}'
    else:
        raise RuntimeError(f"Unsupported default value {value}")


def cpp_type(typ) -> Tuple[str, Set[str], Set[str]]:
    def args_type(base_type: str) -> Tuple[str, Set[str], Set[str]]:
        optional = False
        real_args = ()

        for arg in args:
            if arg is NoneT:
                optional = True
            else:
                real_args += (arg,)

        arg_types = ()
        all_arg_usings = set()
        all_arg_includes = {f"<{base_type.replace('std::', '')}>"}
        if optional:
            all_arg_includes.add("<optional>")

        for arg in real_args:
            arg_type, arg_includes, arg_usings = cpp_type(arg)
            arg_types += (arg_type,)
            all_arg_includes.update(arg_includes)
            all_arg_usings.update(arg_usings)

        args_cpp_type = arg_types[0] if len(arg_types) == 1 else f"{base_type}<{', '.join(arg_types)}>"

        return f"std::optional<{args_cpp_type}>" if optional else args_cpp_type, all_arg_includes, all_arg_usings

    dot = r'.'
    slash = r'/'
    base_cpp_type, include = __base_type_mappings.get(typ, (None, None))
    if base_cpp_type:
        return base_cpp_type, {include} if include else set(), set()
    else:
        origin = get_origin(typ)
        args = get_args(typ)

        if origin is None:
            if typ in (dict, list, set, tuple):
                if args:
                    origin = typ
                else:
                    raise RuntimeError(f"Cannot use non parameterised collection {typ} as a type")
            elif issubclass(typ, (PybindDataclass, PybindBaseModel)) or issubclass(typ, Enum):
                using = "::".join(chain(typ.__module__.split('.')[:-1], (typ.__name__,)))
                return typ.__name__, {f'"{typ.__module__.replace(dot, slash)}.h"'}, {using}
            else:
                raise RuntimeError(f"Can only use builtins, datetime or BaseModel-derived types, not {typ}")

        if origin is Optional:
            cpp_typ, includes, usings = cpp_type(args[0])
            return f"std::optional<{cpp_typ}>", includes.union(("optional",)), usings
        elif origin in (Union, UnionType):
            return args_type("std::variant")
        elif origin in (list, Sequence):
            cpp_typ, includes, usings = cpp_type(args[0])
            return f"std::vector<{cpp_typ}>", includes.union(("vector",)), usings
        elif origin is set:
            cpp_typ, includes, usings = cpp_type(args[0])
            return f"std::set<{cpp_typ}>", includes.union(("set",)), usings
        elif origin is tuple:
            if Ellipsis in args:
                if len(args) != 2 or args[1] is not Ellipsis:
                    raise RuntimeError("Cannot support Ellipsis/Any as a tuple parameter type")

                # We've got something like Tuple[int, ...], treat it as a vector
                cpp_typ, includes, usings = cpp_type(args[0])
                return f"std::vector<{cpp_typ}>", includes.union(("vector",)), usings
            else:
                # An actual tuple
                return args_type("std::tuple")
        elif origin in (dict, Mapping):
            key_type, key_includes, key_usings = cpp_type(args[0])
            value_type, value_includes, value_usings = cpp_type(args[0])
            return f"std::unordered_map<{key_type}, {value_type}>", \
                key_includes.union(value_includes).union("unordered_map", ), key_usings.union(value_usings)
        else:
            raise RuntimeError(f"Cannot handle type {typ}")


def class_attrs(model_class):
    types = []
    kwargs = []
    constructor_args = []
    init_args = []
    default_init_args = []
    struct_members = []
    pydantic_attrs = []
    names = []

    frozen = model_class.__dataclass_params__.frozen if is_dataclass(model_class) else \
        model_class.model_config.get("frozen")
    pydantic_def = ".def_readonly" if frozen else ".def_readwrite"
    all_includes = {'"msgpack/msgpack.h"'}
    all_usings = set()
    bases = [b for b in model_class.__bases__
             if b not in (PybindDataclass, PybindBaseModel) and issubclass(b, (PybindDataclass, PybindBaseModel))]
    base_field_names = set(chain.from_iterable((n for n, _, _ in field_info_iter(b)) for b in bases))
    needs_default_constructor = False

    for name, field_type, default in field_info_iter(model_class):
        typ, includes, usings = cpp_type(field_type)
        all_includes.update(includes)
        all_usings.update(usings)

        try:
            move = field_type not in __no_move_types and not issubclass(field_type, Enum)
        except TypeError:
            move = False

        default = cpp_default(default)
        position = len(types) if default else 0  # Need to ensure non-defaulted params are first
        names.insert(position, name)

        default_suffix = ""
        if default:
            default_suffix = f'={default}'
        else:
            needs_default_constructor = True

        constructor_args.insert(position, f"{typ} {name + default_suffix}")
        kwargs.insert(position, f'py::arg("{name}")' + default_suffix)
        types.insert(position, typ)

        if name not in base_field_names:
            init_args.insert(position, f"{name}({name if not move else f'std::move({name})'})")
            default_init_args.insert(position, f"{name}({default or ''})")
            struct_members.insert(position, f"{typ} {name};")
            pydantic_attrs.insert(position, f'{pydantic_def}("{name}", &{model_class.__name__}::{name})')

    base_init = {b: class_attrs(b)[0] for b in bases}
    return names, constructor_args, init_args, default_init_args if needs_default_constructor else [], base_init, \
        types, kwargs, struct_members, pydantic_attrs, all_includes, all_usings


def generate_class(model_class, indent_size: int = 0, max_width: int = 110) -> \
        Tuple[Optional[str], Optional[str], Optional[Set[str]], Optional[Set[str]]]:

    names, constructor_args, init_args, default_init_args, base_init, types, kwargs, struct_members, pydantic_attrs, \
        all_includes, all_usings = class_attrs(model_class)

    if not types:
        return None, None, None, None

    cls_name = model_class.__name__
    bases = f" : public {', '.join(b.__name__ for b in base_init.keys())}" if base_init else ""
    default_constructor = ""
    default_pydantic_init = ""
    indent = " " * indent_size
    newline = "\n"
    newline_indent = f"{newline}    {indent}"
    init_indent = " " * (indent_size + 8)
    init_wrapper = TextWrapper(break_long_words=False, initial_indent=init_indent, subsequent_indent=init_indent,
                               width=max_width)
    args_indent = " " * (indent_size + 5 + len(cls_name))
    args_wrapper = TextWrapper(break_long_words=False, subsequent_indent=args_indent, width=max_width)

    if default_init_args:
        default_constructor = f"{indent}{cls_name}() :\n"
        default_pydantic_init = f"{indent}.def(py::init<>())\n{indent}"

        if base_init:
            default_constructor += \
                f"{indent}        " + \
                f"{(',        ' + newline + indent).join(base.__name__ + '()' for base in base_init.keys())}" + \
                "," + newline

        default_constructor += "\n".join(init_wrapper.wrap(', '.join(default_init_args)))
        default_constructor += f"""
    {indent}{{
    {indent}}}
    
    """

    base_init_str = ""
    if base_init:
        base_init_str = f"        {indent}" + \
                        f"""{(',' + newline + indent).join(base.__name__ + '(' + ', '.join(args) + ')'
                                                           for base, args in base_init.items())},{newline}"""

    struct_def = f"""{indent}struct {cls_name}{bases}
{indent}{{
    {default_constructor}{indent}{cls_name}({newline.join(args_wrapper.wrap(', '.join(constructor_args)))}) :
{base_init_str}{newline.join(init_wrapper.wrap(', '.join(init_args)))}
    {indent}{{
    {indent}}}

    {indent}{newline_indent.join(struct_members)}
    
    {indent}MSGPACK_DEFINE({newline.join(args_wrapper.wrap(', '.join(names)))});
{indent}}};"""

    pydantic_bases = ", " + ", ".join(base.__name__ for base in base_init.keys()) if base_init else ""
    pydantic_init = "\n".join(args_wrapper.wrap(f"{', '.join(types)}>(), {', '.join(kwargs)}"))
    pydantic_def = f"""{indent}py::class_<{cls_name}{pydantic_bases}>(m, "{cls_name}")
    {default_pydantic_init}{indent}.def(py::init<{pydantic_init})
    {indent}.def("to_msg_pack", &{cls_name}::to_msg_pack)
    {indent}.def_static("from_msg_pack", &{cls_name}::from_msg_pack<{cls_name}>)
    {indent}{newline_indent.join(pydantic_attrs)};"""

    return struct_def, pydantic_def, all_includes, all_usings


def generate_enum(enum_typ: EnumType, indent_size: int = 0, max_width: int = 110) -> Tuple[str, str]:
    name = enum_typ.__name__
    indent = " " * indent_size
    args_indent = indent * 2
    newline_indent = f"\n{args_indent}"
    args_wrapper = TextWrapper(break_long_words=False, subsequent_indent=args_indent, width=max_width)

    items = (f"{i.name} = {i.value}" for i in enum_typ)
    enum_def = "\n".join(args_wrapper.wrap(f"""{indent}enum class {name} {{ {', '.join(items)} }};"""))

    pydantic_items = (f'.value("{i.name}", {name}::{i.name})' for i in enum_typ)
    pydantic_def = f'{indent}py::enum_<{name}>(m, "{name}")'
    pydantic_def += newline_indent + newline_indent.join(pydantic_items) + ";"

    return enum_def, pydantic_def


def generate_module(module_name: str, output_dir: str, indent_size: int = 4, max_width: int = 110):
    dot = r"."
    slash = r"/"
    indent = " " * indent_size
    single_newline = "\n"
    double_newline = "\n\n"
    newline_indent = f"{single_newline}{indent}"

    module = import_module(module_name)
    generated_root = Path(output_dir)
    module_root = module.__name__.split('.')[-0]
    module_base_name = module.__name__.split('.')[-1]
    self_include = f'"{module_name.replace(dot, slash)}.h"'
    include_root = "/".join(module_name.split(".")[:-1])
    qualified_module_name = "_".join(module.__name__.split('.')[:-1]) + "_" + module_base_name
    namespace = "::".join(module_name.split(".")[:-1])
    guard = f"{namespace.upper().replace('::', '_')}_{module_base_name.upper()}_H"

    if not generated_root.exists():
        generated_root.mkdir(parents=True, exist_ok=True)

    includes = set()
    usings = set()
    struct_defs = []
    pydantic_defs = []
    enum_defs = []

    for clz in (v for v in vars(module).values() if isclass(v) and v.__module__ == module.__name__):
        if clz is not Enum and issubclass(clz, Enum):
            enum_def, pydantic_def = generate_enum(clz, indent_size, max_width)
            enum_defs.append(enum_def)
            pydantic_defs.append(pydantic_def)
        elif issubclass(clz, (PybindDataclass, PybindBaseModel)):
            struct_def, pydantic_def, struct_includes, struct_usings = \
                generate_class(clz, indent_size, max_width=max_width)
            if struct_def:
                struct_defs.append(struct_def)
                pydantic_defs.append(pydantic_def)
                includes = includes.union(struct_includes)
                usings = usings.union(struct_usings)

    imports = []
    for include in (i for i in includes if i.startswith('"' + module_root) and include_root not in i):
        import_parts = include.split(slash)
        import_parts.insert(-1, "__pybind__")
        import_qualifier = "_".join(import_parts[:-2]).strip('"')
        import_parts[-1] = import_qualifier + "_" + import_parts[-1].replace(".h", "")
        imprt = ".".join(import_parts)
        imports.append(f"{indent}py::module_::import({imprt});")

    includes = [f"#include {i}" for i in
                chain(sorted(i for i in includes if not i.endswith('.h"')),
                      sorted(i for i in includes if i.endswith('.h"') and i != self_include))]

    usings = [f"using {u};" for u in sorted(usings) if "::".join(u.split("::")[:-1]) != namespace]

    enum_contents = f"\n{double_newline.join(enum_defs)}{single_newline if struct_defs else ''}" if enum_defs else ""
    struct_contents = f"\n{double_newline.join(struct_defs)}" if struct_defs else ""
    include_contents = f"\n{single_newline.join(includes)}\n" if includes else ""
    using_contents = f"\n{indent}{newline_indent.join(usings)}\n" if includes else ""
    import_contents = f"\n{single_newline.join(imports)}\n" if imports else ""

    header_contents = f"""
#ifndef {guard}
#define {guard}
{include_contents}
namespace {namespace}
{{{using_contents}{enum_contents}{struct_contents}
}} // {namespace}

#endif // {guard}
"""

    cpp_contents = f"""
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/chrono.h>

#include "{module_base_name}.h"

namespace py = pybind11;
using namespace {namespace};


PYBIND11_MODULE({qualified_module_name}, m)
{{{import_contents}
{double_newline.join(pydantic_defs)}
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

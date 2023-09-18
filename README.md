# pydantic-bind

# Table of Contents
1. [Overview](#Overview)
2. [No Copy](#No-Copy)
3. [Supported Types](#Supported-Types)
4. [Inheritance](#Inheritance)
5. [Msgpack](#Msgpack)
6. [Generated Code](#Generated-Code)


## Overview

This project has helpers for automatically generating C++ structs and corresponding pybind marshalling code for 
dataclasses and Pydantic-based classes.

This is achieved via a cmake rule: `pydantic_bind_add_module(<path to module>)`

Add a module this way and it will be scanned for:
- dataclasses
- classes derived from Pydantic's BaseModel
- enums

For any of these which are encountered, a definition will be added to a .h file, with relative path matching the module
and [pybind11](https://pybind11.readthedocs.io/en/stable/index.html) code for binding objects added to a
corresponding .cpp file.

The intended use of this package is for defining behaviour-less data classes, to be shared between Python and C++. E.g.,
a common object model for financial modelling.

Note that the typcal Python developer experience is now somewhat changed, in that it's necessary to build/install
the project. I personally use JetBrains CLion, in place of PyCharm for such projects.

You can create an instance of the pybind class from your original using `get_pybind_instance()`, e.g.,

*my_class.py:*

    from dataclasses import dataclass

    @dataclass
    clas MyClass:
        my_int: int
        my_string: str | None

*CMakeLists.txt:*

    cmake_minimum_required(VERSION 3.9)
    project(my_project)
    
    set(CMAKE_CXX_STANDARD 20)
    
    find_package(Python3 REQUIRED COMPONENTS Interpreter Development)
    find_package(pydantic_bind REQUIRED COMPONENTS HINTS "${Python3_SITELIB}")
    
    pydantic_bind_add_module(my_class.py)


*my_util.py*

    from pydantic_bind import get_pybind_value
    from my_class imnport MyClass

    orig = MyClass(my_int=123, my_string="hello")
    generated = get_pybind_value(orig)


## No copy

What if you would like a single representation of the data, shared between C++ and Python. Then fear not,
`base.BaseModelNoCopy` is your friend! Deriving from this class will result in the annotations for the pydantic class
being re-written using `computed_field`, with property getters and setters operating on the generated pybind class.

`BaseModelNoCopy.__init__` will create the corresponding pybind class, using the supplied values.


## Supported types

The following Python -> C++ mappings are supported (there are likely others I should consider):

- bool --> bool
- float --> double
- int --> int
- str --> std::string
- datetime.date --> std::chrono::system_clock::time_point
- datetime.datetime --> std::chrono::system_clock::time_point
- datetime.time --> std::chrono::system_clock::time_point
- datetime.timedelta --> std::chrono::duration
- pydantic.BaseModel --> struct
- pydantic_bind.BaseModelNoCopy --> struct
- dataclass --> struct

## Inheritance

I have tested single inheritance (see [Generated Code](#Generated-code)). Multiple inheritance may work ... or it
may not. I'd generally advise against using it for data classes


## Msgpack

A rather rudimentary msgpack implementation is added to the generated C++ structs, using a slightly modified version
of [cpppack](https://github.com/mikeloomisgg/cppack). It wasn't clear to me whether this package is maintained or
accepting submissions, so I copied and slightly modified `msgpack.h` (also, I couldn't work out how to add to my 
project with my rather rudimentary cmake skillz!) Changes include:

- Fixing includes
- Support for std::optional
- Support for std::variant


## Generated code

Code is generated into a directory structure underneath `<top level>/generated/`

Headers are installed to `<top level>/include`

Compiled pybind modules are installed into `<original module path>/__pybind__/`

For the example below, `common_object_model/common_object_model/v1/common/__pybind__/foo.cpython-311-darwin.so` will
be installed (obviously with corresponding qualifiers for Linux/Windows). `get_pybind_value()` searches this
directory

*common_object_model/common_object_model/v1/common/foo.py:*

    from dataclasses import dataclass
    import datetime as dt
    from enum import Enum, auto
    from typing import Union

    from pydantic_bind import BaseModelNoCopy


    class Weekday(Enum):
        MONDAY = auto()
        TUESDAY = auto()
        WEDNESDAY = auto()
        THURSDAY = auto()
        FRIDAY = auto()
        SATURDAY = auto()
        SUNDAY = auto()
    
    
    @dataclass
    class DCFoo:
        my_int: int
        my_string: str | None
    
    
    class Foo(BaseModelNoCopy):
        my_bool: bool = True
        my_day: Weekday = Weekday.SUNDAY
    
    
    class Bar(Foo):
        my_int: int = 123
        my_string: str
        my_optional_string: str | None = None
    
    
    class Baz(BaseModelNoCopy):
        my_variant: Union[str, float] = 123.
        my_date: dt.date
        my_foo: Foo
        my_dc_foo: DCFoo

will generate the following files:

*common_object_model/generated/common_object_model/v1/common/foo.h:*

    #ifndef COMMON_OBJECT_MODEL_FOO_H
    #define COMMON_OBJECT_MODEL_FOO_H
    
    #include <string>
    #include <optional>
    #include <variant>
    #include <msgpack/msgpack.h>
    #include <chrono>
    
    namespace common_object_model
    {
        enum Weekday { MONDAY = 1, TUESDAY = 2, WEDNESDAY = 3, THURSDAY = 4, FRIDAY = 5, SATURDAY = 6, SUNDAY = 7
        };
    
        struct DCFoo
        {
            DCFoo() :
                my_string(), my_int()
            {
            }
        
            DCFoo(std::optional<std::string> my_string, int my_int) :
                my_string(my_string), my_int(my_int)
            {
            }
    
            std::optional<std::string> my_string;
            int my_int;
        
            MSGPACK_DEFINE(my_string, my_int);
        };
    
        struct Foo
        {
            Foo(bool my_bool=true, Weekday my_day=SUNDAY) :
                my_bool(my_bool), my_day(my_day)
            {
            }
    
            bool my_bool;
            Weekday my_day;
        
            MSGPACK_DEFINE(my_bool, my_day);
        };
    
        struct Bar : public Foo
        {
            Bar() :
                Foo(),
                my_string(), my_int(123), my_optional_string(std::nullopt)
            {
            }
        
            Bar(std::string my_string, bool my_bool=true, Weekday my_day=SUNDAY, int my_int=123, std::optional<std::string>
                my_optional_string=std::nullopt) :
                Foo(my_bool, my_day),
                my_string(std::move(my_string)), my_int(my_int), my_optional_string(my_optional_string)
            {
            }
    
            std::string my_string;
            int my_int;
            std::optional<std::string> my_optional_string;
        
            MSGPACK_DEFINE(my_string, my_bool, my_day, my_int, my_optional_string);
        };
    
        struct Baz
        {
            Baz() :
                my_dc_foo(), my_foo(), my_date(), my_variant(123.0)
            {
            }
        
            Baz(DCFoo my_dc_foo, Foo my_foo, std::chrono::system_clock::time_point my_date, std::variant<std::string, double>
                my_variant=123.0) :
                my_dc_foo(std::move(my_dc_foo)), my_foo(std::move(my_foo)), my_date(my_date),
                my_variant(my_variant)
            {
            }
    
            DCFoo my_dc_foo;
            Foo my_foo;
            std::chrono::system_clock::time_point my_date;
            std::variant<std::string, double> my_variant;
        
            MSGPACK_DEFINE(my_dc_foo, my_foo, my_date, my_variant);
        };
    } // common_object_model
    
    #endif // COMMON_OBJECT_MODEL_FOO_H


*common_object_model/generated/common_object_model/v1/common/foo.cpp:*

    #include <pybind11/pybind11.h>
    #include <pybind11/stl.h>
    #include <pybind11/chrono.h>
    
    #include "foo.h"
    
    namespace py = pybind11;
    using namespace common_object_model;
    
    
    PYBIND11_MODULE(foo, m)
    {
        py::enum_<Weekday>(m, "Weekday").value("MONDAY", Weekday::MONDAY)
            .value("TUESDAY", Weekday::TUESDAY)
            .value("WEDNESDAY", Weekday::WEDNESDAY)
            .value("THURSDAY", Weekday::THURSDAY)
            .value("FRIDAY", Weekday::FRIDAY)
            .value("SATURDAY", Weekday::SATURDAY)
            .value("SUNDAY", Weekday::SUNDAY);

        py::class_<DCFoo>(m, "DCFoo")
            .def(py::init<std::optional<std::string>, int>(), py::arg("my_string"), py::arg("my_int"))
            .def_readwrite("my_string", &DCFoo::my_string)
            .def_readwrite("my_int", &DCFoo::my_int);
    
        py::class_<Foo>(m, "Foo")
            .def(py::init<bool, Weekday>(), py::arg("my_bool")=true, py::arg("my_day")=SUNDAY)
            .def_readwrite("my_bool", &Foo::my_bool)
            .def_readwrite("my_day", &Foo::my_day);
    
        py::class_<Bar>(m, "Bar")
            .def(py::init<std::string, bool, Weekday, int, std::optional<std::string>>(), py::arg("my_string"), py::arg("my_bool")=true,
                py::arg("my_day")=SUNDAY, py::arg("my_int")=123, py::arg("my_optional_string")=std::nullopt)
            .def_readwrite("my_string", &Bar::my_string)
            .def_readwrite("my_int", &Bar::my_int)
            .def_readwrite("my_optional_string", &Bar::my_optional_string);
    
        py::class_<Baz>(m, "Baz")
            .def(py::init<DCFoo, Foo, std::chrono::system_clock::time_point, std::variant<std::string, double>>(), py::arg("my_dc_foo"),
                py::arg("my_foo"), py::arg("my_date"), py::arg("my_variant")=123.0)
            .def_readwrite("my_dc_foo", &Baz::my_dc_foo)
            .def_readwrite("my_foo", &Baz::my_foo)
            .def_readwrite("my_date", &Baz::my_date)
            .def_readwrite("my_variant", &Baz::my_variant);
    }





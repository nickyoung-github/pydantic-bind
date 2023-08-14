# pydantic-bind

This project has helpers for automatically generating C++ structs and corresponding pybind marshalling code for Pydantic-based classes.

This is achieved via a cmake rule: pydantic_bind_add_module(<path to module>)

Add a module this way and it will be scanned for any classes which are a subclass of pydantic.BaseModel and a .h (containing the Struct definition)
and .cpp (containing the pybind code) will be generated and added to the project

There is also a new base class: BaseModelNoCopy. Deriving from this class will cause your annotations to be re-written as properties, which
get/set the corresponding members on the generated Struct, via pybind

More to come etc

find_package(Python3 REQUIRED COMPONENTS Interpreter Development)
find_package(pybind11 REQUIRED)

include_directories("${Python3_SITELIB}/pydantic_bind/include")


function(pydantic_bind_add_module)
    cmake_path(GET ARGN FILENAME target_name)
    cmake_path(REMOVE_EXTENSION target_name OUTPUT_VARIABLE target_name)

    cmake_path(REPLACE_EXTENSION ARGN cpp OUTPUT_VARIABLE target_cpp)
    cmake_path(REPLACE_EXTENSION target_cpp h OUTPUT_VARIABLE target_header)

    cmake_path(REMOVE_EXTENSION target_cpp OUTPUT_VARIABLE module)
    string(REPLACE "/" "." module ${module})

    set(target_cpp "${PROJECT_SOURCE_DIR}/generated/${target_cpp}")
    set(target_header "${PROJECT_SOURCE_DIR}/generated/${target_header}")
    cmake_path(REMOVE_FILENAME target_cpp OUTPUT_VARIABLE output_dir)

    string(REPLACE "generated/" "" pybind_dir ${output_dir})
    set(pybind_dir "${pybind_dir}__pybind__")

    add_custom_command(
            OUTPUT ${target_cpp} ${target_header}
            DEPENDS ${ARGN}
            COMMAND ${CMAKE_COMMAND} -E env PYTHONPATH="${PROJECT_SOURCE_DIR}" ${Python3_EXECUTABLE} "${Python3_SITELIB}/pydantic_bind/cpp_generator.py" --module ${module} --output_dir ${output_dir}
    )

    pybind11_add_module(${target_name} "${target_cpp}")
    set_target_properties(${target_name} PROPERTIES PUBLIC_HEADER "${target_header}")

    install(TARGETS ${target_name}
            DESTINATION ${pybind_dir}
            PUBLIC_HEADER DESTINATION "${PROJECT_SOURCE_DIR}/include")
endfunction()


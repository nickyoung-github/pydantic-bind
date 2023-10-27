
find_package(Python3 REQUIRED COMPONENTS Interpreter Development)
find_package(pybind11 REQUIRED HINTS "${Python3_SITELIB}")

include_directories("${Python3_SITELIB}/pydantic_bind/include")
include_directories("${PROJECT_SOURCE_DIR}/generated")

function(_pydantic_generate_cpp package)
    string(REPLACE "." "/" package_root ${package})
    string(REPLACE "." "_" package_name ${package})

    cmake_path(APPEND generated_dir ${PROJECT_SOURCE_DIR} "generated" ${package_root})
    cmake_path(APPEND header_dir ${PROJECT_SOURCE_DIR} "include" ${package_root})
    cmake_path(APPEND pybind_dir ${PROJECT_SOURCE_DIR} ${package_root} "__pybind__")

    foreach (module_path ${ARGN})
        string(REPLACE "${PROJECT_SOURCE_DIR}/" "" module_r_path ${module_path})

        cmake_path(REMOVE_EXTENSION module_r_path OUTPUT_VARIABLE module)
        cmake_path(GET module FILENAME base_name)
        string(REPLACE "/" "." module ${module})

        string(CONCAT target ${package_name} "_" ${base_name})

        cmake_path(APPEND foo ${generated_dir} ${base_name} OUTPUT_VARIABLE cpp)
        cmake_path(APPEND_STRING cpp ".cpp")

        cmake_path(REPLACE_EXTENSION cpp h OUTPUT_VARIABLE header)
        install(FILES ${header} DESTINATION ${header_dir})

        add_custom_command(
                OUTPUT ${cpp} ${header}
                DEPENDS ${module_path}
                COMMAND ${CMAKE_COMMAND} -E env PYTHONPATH="${PROJECT_SOURCE_DIR}" ${Python3_EXECUTABLE} "${Python3_SITELIB}/pydantic_bind/cpp_generator.py" --module ${module} --output_dir ${generated_dir}
        )

        list(APPEND cpps ${cpp})
        list(APPEND headers ${header})
        list(APPEND targets ${target})
        list(APPEND pybind_dirs ${pybind_dir})
    endforeach()

    set(package_cpps ${cpps} PARENT_SCOPE)
    set(package_headers ${headers} PARENT_SCOPE)
    set(package_targets ${targets} PARENT_SCOPE)
    set(package_pybind_dirs ${pybind_dirs} PARENT_SCOPE)
endfunction()

function(pydantic_bind_add_package package)
    string(REPLACE "." "/" package_root ${package})

    file(GLOB_RECURSE dirs LIST_DIRECTORIES true "${PROJECT_SOURCE_DIR}/${package_root}/INVALID")

    file(GLOB root "${PROJECT_SOURCE_DIR}/${package_root}/*.py")
    list(FILTER root EXCLUDE REGEX ".*\/__init__.py")
    list(LENGTH root root_len)

    if (${root_len} GREATER 0)
        list(APPEND dirs "${PROJECT_SOURCE_DIR}/${package_root}")
    endif()

    list(FILTER dirs EXCLUDE REGEX ".*\/__pycache__")
    list(FILTER dirs EXCLUDE REGEX ".*\/__pybind__")

    # First, generate all the cpp files from python

    foreach (dir ${dirs})
        cmake_path(GET dir FILENAME dir_name)
        string(REPLACE "${PROJECT_SOURCE_DIR}/" "" sub_package ${dir})
        string(REPLACE "/" "." sub_package ${sub_package})

        file(GLOB modules ${dir}/*.py)
        list(FILTER modules EXCLUDE REGEX ".*\/__init__.py")
        list(LENGTH modules module_len)

        if (${module_len} GREATER 0)
            _pydantic_generate_cpp(${sub_package} ${modules})

            list(APPEND all_cpps ${package_cpps})
            list(APPEND all_headers ${package_headers})
            list(APPEND all_targets ${package_targets})
            list(APPEND all_pybind_dirs ${package_pybind_dirs})
        endif()
    endforeach()

    # Now, create pybind11 targets for each module

    foreach(cpp target pybind_dir IN ZIP_LISTS all_cpps all_targets all_pybind_dirs)
        pybind11_add_module(${target} ${cpp} ${all_headers})
        install(TARGETS ${target} DESTINATION ${pybind_dir})
        target_include_directories(${target} INTERFACE "${Python3_SITELIB}/pydantic_bind/include")
    endforeach()
endfunction()
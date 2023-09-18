find_package(Python3 REQUIRED COMPONENTS Interpreter Development)
find_package(pybind11 REQUIRED HINTS "${Python3_SITELIB}")

function(pydantic_bind_add_module target_name)
    set(generated_root "${PROJECT_SOURCE_DIR}/generated")

    set(module ${ARGN})
    string(REPLACE ".py" ".cpp" target_cpp "${generated_root}/${ARGN}")
    string(REPLACE "../.." "../../pydantic_bind" target_cpp ${target_cpp})
    string(REPLACE ".cpp" ".h" target_header ${target_cpp})

    add_custom_command(
        OUTPUT "${PROJECT_SOURCE_DIR}/${target_cpp}" "${PROJECT_SOURCE_DIR}/${target_header}"
        DEPENDS ${ARGN}
        COMMAND ${CMAKE_COMMAND} -E env PYTHONPATH=${PROJECT_SOURCE_DIR} python "../../pydantic_bind/cpp_generator.py" -n ${target_name} --m ${module} -o ${output_dir}
        VERBATIM
    )

    pybind11_add_module(${target_name} "${PROJECT_SOURCE_DIR}/${target_cpp}")
    set_target_properties(${target_name} PROPERTIES PUBLIC_HEADER "${PROJECT_SOURCE_DIR}/${target_header}")

    install(TARGETS ${target_name} COMPONENT python LIBRARY DESTINATION "../..")
endfunction()

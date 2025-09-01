find_package(Python3 REQUIRED COMPONENTS Interpreter)

set(GENERATED_DIR "${CMAKE_CURRENT_BINARY_DIR}/generated")
file(MAKE_DIRECTORY "${GENERATED_DIR}")

set(GENERATED_SOURCES
    "${GENERATED_DIR}/messages.h"
    "${GENERATED_DIR}/messages.cpp"
    "${GENERATED_DIR}/message_registry.h"
    "${GENERATED_DIR}/message_registry.cpp"
)

add_custom_command(
    OUTPUT ${GENERATED_SOURCES}
    COMMAND ${Python3_EXECUTABLE}
        "${CMAKE_CURRENT_SOURCE_DIR}/generate_messages.py"
        "${CMAKE_CURRENT_SOURCE_DIR}/messages.def"
        "${GENERATED_DIR}"
    DEPENDS
        "${CMAKE_CURRENT_SOURCE_DIR}/generate_messages.py"
        "${CMAKE_CURRENT_SOURCE_DIR}/messages.def"
    WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    COMMENT "Generating message classes from messages.def"
    VERBATIM
)

add_custom_target(proto_gen DEPENDS ${GENERATED_SOURCES})

add_library(proto_msgs STATIC
    proto/registry.cpp
    proto/validation.cpp
    ${GENERATED_SOURCES}
)
target_include_directories(proto_msgs PUBLIC
    "${CMAKE_CURRENT_SOURCE_DIR}"
    "${GENERATED_DIR}"
)
target_link_libraries(proto_msgs PUBLIC core)
add_dependencies(proto_msgs proto_gen)

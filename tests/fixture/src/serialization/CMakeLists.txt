add_library(serialization STATIC
    encoder.cpp
    decoder.cpp
)
target_include_directories(serialization PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/..)
target_link_libraries(serialization PUBLIC proto_msgs core)

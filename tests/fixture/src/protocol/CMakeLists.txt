add_library(protocol STATIC
    handler.cpp
    connection.cpp
)
target_include_directories(protocol PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/..)
target_link_libraries(protocol PUBLIC serialization logging)

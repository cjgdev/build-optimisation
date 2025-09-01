add_library(logging STATIC
    logger.cpp
    sink.cpp
)
target_include_directories(logging PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/..)
target_link_libraries(logging PRIVATE core)

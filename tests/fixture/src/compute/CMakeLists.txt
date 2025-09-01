add_library(compute STATIC
    pipeline.cpp
    scheduler.cpp
)
target_include_directories(compute PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/..)
target_link_libraries(compute PRIVATE math_lib platform)

add_library(platform STATIC
    filesystem.cpp
    thread_pool.cpp
)
target_include_directories(platform PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/..)
target_link_libraries(platform PRIVATE core)

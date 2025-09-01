add_executable(benchmark bench_main.cpp)
target_include_directories(benchmark PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/..)
target_link_libraries(benchmark PRIVATE engine math_lib)

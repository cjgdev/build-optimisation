add_executable(test_runner
    test_main.cpp
    test_protocol.cpp
    test_compute.cpp
)
target_include_directories(test_runner PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/..)
target_link_libraries(test_runner PRIVATE engine protocol)

add_library(core STATIC
    types.cpp
    assert.cpp
    string_utils.cpp
)
target_include_directories(core PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/..)
target_link_libraries(core PUBLIC config_iface)

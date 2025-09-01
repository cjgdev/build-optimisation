add_library(plugin_api SHARED
    plugin_api.cpp
    plugin_registry.cpp
)
target_include_directories(plugin_api PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/..)
target_link_libraries(plugin_api PRIVATE core logging)

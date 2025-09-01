add_library(math_objs OBJECT
    helpers/interpolation.cpp
    helpers/constants.cpp
)
target_include_directories(math_objs PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/..)
target_link_libraries(math_objs PRIVATE core)

add_library(math_lib STATIC
    matrix.cpp
    vector.cpp
    transforms.cpp
    $<TARGET_OBJECTS:math_objs>
)
target_include_directories(math_lib PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/..)
target_link_libraries(math_lib PRIVATE core math_objs)

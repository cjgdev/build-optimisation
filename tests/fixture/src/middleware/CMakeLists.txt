add_library(middleware STATIC
    request_router.cpp
    metrics_collector.cpp
    service_registry.cpp
    rate_limiter.cpp
)
target_include_directories(middleware PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/..)
target_link_libraries(middleware PUBLIC protocol compute logging)

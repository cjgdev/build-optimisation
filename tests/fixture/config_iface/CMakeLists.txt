add_library(config_iface INTERFACE)
target_compile_definitions(config_iface INTERFACE
    PROJECT_VERSION="1.0.0"
    DEBUG_LEVEL=0
)

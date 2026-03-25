# toolchain.cmake — rendered from config.yaml by config.py
#
# Hardcoded compiler and binutils paths for CMake.
# Each path is substituted from the "compiler" section of config.yaml.
#
# Do not modify manually — regenerate via config.py.

# Compilers
set(CMAKE_C_COMPILER   "@CC@")
set(CMAKE_CXX_COMPILER "@CXX@")

# Binutils — explicitly set so CMake does not fall back to
# system versions. Mismatched binutils can cause subtle
# linking and archiving issues.
set(CMAKE_AR      "@AR@")
set(CMAKE_RANLIB  "@RANLIB@")
set(CMAKE_NM      "@NM@")
set(CMAKE_OBJDUMP "@OBJDUMP@")
set(CMAKE_STRIP   "@STRIP@")
set(CMAKE_LINKER  "@LINKER@")

# Prevent CMake from searching system-default environment paths
# for compilers and tools. All tooling comes from the paths above.
set(CMAKE_FIND_USE_SYSTEM_ENVIRONMENT_PATH OFF)

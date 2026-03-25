# toolchain.cmake — rendered from config.yaml by config.py
#
# Configures CMake to use Red Hat Developer Toolset 12.
# All paths are derived from DEVTOOLSET_ROOT to ensure the
# compiler and binutils are version-matched.
#
# This file replaces sourcing /opt/rh/gcc-toolset-12/enable.
# Do not modify manually — regenerate via config.py.

set(DEVTOOLSET_ROOT "@GCC_TOOLSET_ROOT@")

# Compilers
set(CMAKE_C_COMPILER   "${DEVTOOLSET_ROOT}/usr/bin/gcc")
set(CMAKE_CXX_COMPILER "${DEVTOOLSET_ROOT}/usr/bin/g++")

# Binutils — explicitly set so CMake does not fall back to
# system versions. Mismatched binutils can cause subtle
# linking and archiving issues.
set(CMAKE_AR      "${DEVTOOLSET_ROOT}/usr/bin/ar")
set(CMAKE_RANLIB  "${DEVTOOLSET_ROOT}/usr/bin/ranlib")
set(CMAKE_NM      "${DEVTOOLSET_ROOT}/usr/bin/nm")
set(CMAKE_OBJDUMP "${DEVTOOLSET_ROOT}/usr/bin/objdump")
set(CMAKE_STRIP   "${DEVTOOLSET_ROOT}/usr/bin/strip")
set(CMAKE_LINKER  "${DEVTOOLSET_ROOT}/usr/bin/ld")

# Prevent CMake from searching system-default environment paths
# for compilers and tools. All tooling comes from the toolset.
set(CMAKE_FIND_USE_SYSTEM_ENVIRONMENT_PATH OFF)

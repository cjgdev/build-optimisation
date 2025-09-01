#include "core/assert.h"

#include <iostream>
#include <cstdlib>

[[noreturn]] void assertion_failed(const char* expr, const char* file, int line) {
    std::cerr << "Assertion failed: " << expr
              << " at " << file << ":" << line << "\n";
    std::abort();
}

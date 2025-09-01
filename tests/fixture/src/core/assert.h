#ifndef FIXTURE_CORE_ASSERT_H
#define FIXTURE_CORE_ASSERT_H

#include <string>

[[noreturn]] void assertion_failed(const char* expr, const char* file, int line);

#define FIXTURE_ASSERT(cond) \
    do { if (!(cond)) assertion_failed(#cond, __FILE__, __LINE__); } while(0)

#endif // FIXTURE_CORE_ASSERT_H

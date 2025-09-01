#include "engine/engine.h"
#include <iostream>

static int tests_run = 0;
static int tests_passed = 0;

void report(const char* name, bool passed) {
    tests_run++;
    if (passed) {
        tests_passed++;
        std::cout << "  PASS: " << name << std::endl;
    } else {
        std::cout << "  FAIL: " << name << std::endl;
    }
}

extern void test_protocol_suite();
extern void test_compute_suite();

int main() {
    std::cout << "Running fixture tests..." << std::endl;

    test_protocol_suite();
    test_compute_suite();

    std::cout << tests_passed << "/" << tests_run << " tests passed" << std::endl;
    return (tests_passed == tests_run) ? 0 : 1;
}

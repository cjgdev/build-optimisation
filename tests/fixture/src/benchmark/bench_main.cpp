// NOTE: This file deliberately does NOT include any math/ headers.
// benchmark links math_lib in CMakeLists.txt but never uses it.
// This exercises unused dependency detection in the analysis.

#include "engine/engine.h"
#include <iostream>
#include <chrono>

int main() {
    Engine engine;
    engine.initialize();

    auto start = std::chrono::steady_clock::now();

    for (int i = 0; i < 1000; ++i) {
        engine.process_request("bench", "payload");
    }

    auto end = std::chrono::steady_clock::now();
    auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(end - start).count();

    std::cout << "1000 requests in " << ms << "ms" << std::endl;

    engine.shutdown();
    return 0;
}

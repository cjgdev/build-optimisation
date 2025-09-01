#include "engine/engine.h"
#include "logging/logger.h"
#include "logging/sink.h"
#include <memory>
#include <iostream>

int main() {
    Logger::instance().add_sink(std::make_shared<ConsoleSink>());
    Logger::instance().info("Application starting");

    Engine engine;
    if (!engine.initialize()) {
        Logger::instance().error("Failed to initialize engine");
        return 1;
    }

    auto result = engine.process_request("ping", "hello");
    std::cout << "Result: " << result << std::endl;

    engine.shutdown();
    Logger::instance().info("Application shutdown complete");
    return 0;
}

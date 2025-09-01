#include "logging/logger.h"

static const char* level_to_string(Level level) {
    switch (level) {
        case Level::DEBUG: return "DEBUG";
        case Level::INFO:  return "INFO";
        case Level::WARN:  return "WARN";
        case Level::ERROR: return "ERROR";
    }
    return "UNKNOWN";
}

void Logger::log(Level level, const std::string& message) {
    std::string formatted = std::string("[") + level_to_string(level) + "] " + message;
    for (auto& sink : sinks_) {
        sink->write(formatted);
    }
}

void Logger::add_sink(std::shared_ptr<Sink> sink) {
    sinks_.push_back(std::move(sink));
}

Logger& Logger::instance() {
    static Logger logger;
    return logger;
}

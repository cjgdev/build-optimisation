#ifndef FIXTURE_LOGGING_LOGGER_H
#define FIXTURE_LOGGING_LOGGER_H

#include <memory>
#include <vector>
#include <string>
#include "logging/sink.h"

enum class Level { DEBUG, INFO, WARN, ERROR };

class Logger {
public:
    void log(Level level, const std::string& message);
    void debug(const std::string& message) { log(Level::DEBUG, message); }
    void info(const std::string& message)  { log(Level::INFO,  message); }
    void warn(const std::string& message)  { log(Level::WARN,  message); }
    void error(const std::string& message) { log(Level::ERROR, message); }

    void add_sink(std::shared_ptr<Sink> sink);
    static Logger& instance();

private:
    std::vector<std::shared_ptr<Sink>> sinks_;
};

#endif // FIXTURE_LOGGING_LOGGER_H

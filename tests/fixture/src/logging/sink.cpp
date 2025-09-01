#include "logging/sink.h"
#include <iostream>

void ConsoleSink::write(const std::string& message) {
    std::cout << message << std::endl;
}

FileSink::FileSink(const std::string& filename)
    : stream_(filename, std::ios::app) {}

void FileSink::write(const std::string& message) {
    stream_ << message << "\n";
}

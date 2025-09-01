#ifndef FIXTURE_LOGGING_SINK_H
#define FIXTURE_LOGGING_SINK_H

#include <string>
#include <fstream>
#include <memory>

class Sink {
public:
    virtual ~Sink() = default;
    virtual void write(const std::string& message) = 0;
};

class ConsoleSink : public Sink {
public:
    void write(const std::string& message) override;
};

class FileSink : public Sink {
public:
    explicit FileSink(const std::string& filename);
    void write(const std::string& message) override;

private:
    std::ofstream stream_;
};

#endif // FIXTURE_LOGGING_SINK_H

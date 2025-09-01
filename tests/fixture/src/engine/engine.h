#ifndef FIXTURE_ENGINE_ENGINE_H
#define FIXTURE_ENGINE_ENGINE_H

#include <string>

class Engine {
public:
    Engine();
    ~Engine();

    bool initialize();
    void shutdown();
    std::string process_request(const std::string& request, const std::string& payload);
    bool is_running() const;

private:
    bool running_ = false;
};

#endif

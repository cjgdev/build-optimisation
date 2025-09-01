#include "engine/engine.h"
#include "middleware/request_router.h"
#include "middleware/service_registry.h"
#include "middleware/metrics_collector.h"
#include "middleware/rate_limiter.h"

Engine::Engine() = default;
Engine::~Engine() = default;

bool Engine::initialize() {
    running_ = true;
    return true;
}

void Engine::shutdown() {
    running_ = false;
}

std::string Engine::process_request(const std::string& request,
                                     const std::string& payload) {
    if (!running_) {
        return "error: engine not running";
    }
    RequestRouter router;
    router.add_route(request, [](const std::string& p) { return "ok:" + p; });
    return router.route(request, payload);
}

bool Engine::is_running() const {
    return running_;
}

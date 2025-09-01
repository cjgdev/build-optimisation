#ifndef FIXTURE_MIDDLEWARE_RATE_LIMITER_H
#define FIXTURE_MIDDLEWARE_RATE_LIMITER_H

// ============================================================
// middleware/rate_limiter.h  --  Per-client request throttle
// ============================================================
//
// Engine-facing cluster: depends on compute/scheduler.h
// Enforces per-client request-rate limits using a sliding
// time window tracked via std::chrono.
//
// ============================================================

#include "compute/scheduler.h"
#include <chrono>
#include <map>
#include <string>

// ------------------------------------------------------------
// RateLimiter
//
// Associates each client_id with a maximum requests-per-second
// limit and a rolling counter.  The allow() method returns
// true only when the client has not exceeded its quota within
// the current one-second window.
// ------------------------------------------------------------

class RateLimiter
{
public:

    // --------------------------------------------------------
    // Configure the limit for client_id.
    // Creates a new entry if client_id is not yet known.
    // --------------------------------------------------------
    void set_limit(const std::string& client_id, int max_requests_per_second);

    // --------------------------------------------------------
    // Returns true if the client is within its rate limit and
    // increments the counter; false if the limit is exceeded.
    // Unknown clients are allowed by default (no limit set).
    // --------------------------------------------------------
    bool allow(const std::string& client_id);

    // --------------------------------------------------------
    // Reset the counter and window for client_id so that
    // subsequent calls to allow() start a fresh window.
    // --------------------------------------------------------
    void reset(const std::string& client_id);

private:

    struct ClientState
    {
        int max_rps       = 0;
        int request_count = 0;
        std::chrono::steady_clock::time_point last_reset{};
    };

    std::map<std::string, ClientState> clients_;

};  // class RateLimiter

#endif // FIXTURE_MIDDLEWARE_RATE_LIMITER_H

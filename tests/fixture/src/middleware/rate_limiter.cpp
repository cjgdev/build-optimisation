#include "middleware/rate_limiter.h"

// ============================================================
// middleware/rate_limiter.cpp  --  RateLimiter implementation
// ============================================================
//
// Engine-facing cluster.
// Uses std::chrono::steady_clock to track the one-second
// sliding window per client.
//
// ============================================================

// ------------------------------------------------------------
// set_limit
//
// Inserts or overwrites the ClientState for client_id,
// preserving any existing window timing to avoid races.
// ------------------------------------------------------------
void RateLimiter::set_limit(const std::string& client_id,
                             int max_requests_per_second)
{
    auto& state        = clients_[client_id];
    state.max_rps      = max_requests_per_second;
    // Reset counters whenever the limit configuration changes.
    state.request_count = 0;
    state.last_reset   = std::chrono::steady_clock::now();
}

// ------------------------------------------------------------
// allow
//
// Checks whether client_id is within its configured rate
// limit for the current one-second window.
//
// Unknown clients (no limit configured) are always allowed.
// ------------------------------------------------------------
bool RateLimiter::allow(const std::string& client_id)
{
    auto it = clients_.find(client_id);
    if (it == clients_.end())
    {
        return true;  // No limit configured — allow by default.
    }

    ClientState& state = it->second;
    const auto now     = std::chrono::steady_clock::now();
    const auto elapsed = std::chrono::duration_cast<std::chrono::seconds>(
                             now - state.last_reset).count();

    if (elapsed >= 1)
    {
        // New window: reset counter.
        state.request_count = 0;
        state.last_reset    = now;
    }

    if (state.request_count >= state.max_rps)
    {
        return false;  // Limit exceeded for this window.
    }

    ++state.request_count;
    return true;
}

// ------------------------------------------------------------
// reset
//
// Forces the start of a fresh window for client_id.
// No-op if client_id is not registered.
// ------------------------------------------------------------
void RateLimiter::reset(const std::string& client_id)
{
    auto it = clients_.find(client_id);
    if (it == clients_.end())
    {
        return;
    }

    it->second.request_count = 0;
    it->second.last_reset    = std::chrono::steady_clock::now();
}

#ifndef FIXTURE_MIDDLEWARE_REQUEST_ROUTER_H
#define FIXTURE_MIDDLEWARE_REQUEST_ROUTER_H

// ============================================================
// middleware/request_router.h  --  HTTP-style request router
// ============================================================
//
// Protocol-facing cluster: depends on protocol/handler.h
// Routes incoming requests to registered path handlers.
//
// ============================================================

#include "protocol/handler.h"
#include <string>
#include <vector>

// ------------------------------------------------------------
// RequestRouter
//
// Maps URL-style path strings to Handler callbacks.  Delegates
// dispatch to an internal Handler instance so that the full
// command-registration and dispatch logic lives in protocol/.
// ------------------------------------------------------------

class RequestRouter
{
public:

    // --------------------------------------------------------
    // Register a callback for the given path.
    // Replaces any previously registered callback for path.
    // --------------------------------------------------------
    void add_route(const std::string& path, Handler::Callback handler);

    // --------------------------------------------------------
    // Route a request: dispatch path+payload and return the
    // response produced by the registered callback.
    // Returns an empty string if no route is registered.
    // --------------------------------------------------------
    std::string route(const std::string& path, const std::string& payload) const;

    // --------------------------------------------------------
    // Returns the list of currently registered route paths.
    // --------------------------------------------------------
    std::vector<std::string> registered_routes() const;

private:

    Handler handler_;

};  // class RequestRouter

#endif // FIXTURE_MIDDLEWARE_REQUEST_ROUTER_H

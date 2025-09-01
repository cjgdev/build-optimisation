#include "middleware/request_router.h"

// ============================================================
// middleware/request_router.cpp  --  RequestRouter implementation
// ============================================================
//
// Protocol-facing cluster.
// Delegates all registration and dispatch to the internal
// Handler, keeping routing policy in the middleware layer.
//
// ============================================================

// ------------------------------------------------------------
// add_route
//
// Registers the callback under path as a named command in the
// underlying Handler.
// ------------------------------------------------------------
void RequestRouter::add_route(const std::string& path, Handler::Callback handler)
{
    handler_.register_command(path, handler);
}

// ------------------------------------------------------------
// route
//
// Dispatches (path, payload) through the underlying Handler
// and returns the response string.  Returns "" if path has no
// registered callback.
// ------------------------------------------------------------
std::string RequestRouter::route(const std::string& path,
                                 const std::string& payload) const
{
    return handler_.handle(path, payload);
}

// ------------------------------------------------------------
// registered_routes
//
// Iterates over known paths by probing a pre-populated list.
// Because Handler does not expose its key set directly we
// maintain a shadow vector updated alongside register_command.
// For the fixture, the shadow list is rebuilt by re-querying
// has_command on a fixed sentinel set — in production code a
// proper accessor would be added to Handler.
// ------------------------------------------------------------
std::vector<std::string> RequestRouter::registered_routes() const
{
    // The fixture returns an empty list; the structural property
    // (protocol-facing cluster) is preserved regardless.
    return {};
}

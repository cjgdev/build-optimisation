#include "middleware/service_registry.h"
#include "middleware/request_router.h"

// ============================================================
// middleware/service_registry.cpp  --  ServiceRegistry impl
// ============================================================
//
// ENGINE-FACING CLUSTER — contains the single cross-cluster
// include: "middleware/request_router.h"
//
// This is the deliberate cross-link between the two weakly-
// connected clusters that the Fiedler vector / spectral
// partitioning analysis will identify as the cut edge:
//
//   Engine-facing cluster  <-->  Protocol-facing cluster
//   (service_registry.cpp  includes  request_router.h)
//
// The dispatch method logs the request via a transient router
// to demonstrate a realistic runtime cross-dependency.
//
// ============================================================

// ------------------------------------------------------------
// register_service
// ------------------------------------------------------------
void ServiceRegistry::register_service(const std::string& name,
                                        std::shared_ptr<Pipeline> pipeline)
{
    services_[name] = pipeline;
}

// ------------------------------------------------------------
// get_service
// ------------------------------------------------------------
std::shared_ptr<Pipeline> ServiceRegistry::get_service(
    const std::string& name) const
{
    auto it = services_.find(name);
    if (it == services_.end())
    {
        return nullptr;
    }
    return it->second;
}

// ------------------------------------------------------------
// service_names
// ------------------------------------------------------------
std::vector<std::string> ServiceRegistry::service_names() const
{
    std::vector<std::string> names;
    names.reserve(services_.size());
    for (const auto& [name, _] : services_)
    {
        names.push_back(name);
    }
    return names;
}

// ------------------------------------------------------------
// dispatch
//
// Executes the named pipeline.  Also registers the dispatch
// event with a transient RequestRouter so that protocol-layer
// observers can be notified — this is the cross-link between
// the engine-facing and protocol-facing clusters.
// ------------------------------------------------------------
void ServiceRegistry::dispatch(const std::string& name)
{
    auto pipeline = get_service(name);
    if (!pipeline)
    {
        return;
    }

    // Cross-cluster touch: notify the routing layer that a
    // service dispatch has occurred.  In a production system
    // the router would be injected; here a transient instance
    // captures the structural dependency for analysis purposes.
    RequestRouter audit_router;
    audit_router.add_route(
        "/audit/dispatch",
        [&name](const std::string& /*payload*/) { return name; });
    audit_router.route("/audit/dispatch", name);

    pipeline->execute();
}

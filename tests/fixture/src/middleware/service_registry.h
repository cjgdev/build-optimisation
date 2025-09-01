#ifndef FIXTURE_MIDDLEWARE_SERVICE_REGISTRY_H
#define FIXTURE_MIDDLEWARE_SERVICE_REGISTRY_H

// ============================================================
// middleware/service_registry.h  --  Named pipeline registry
// ============================================================
//
// Engine-facing cluster: depends on compute/pipeline.h
// Maintains a map of named Pipeline instances that can be
// looked up and dispatched by the middleware layer.
//
// ============================================================

#include "compute/pipeline.h"
#include <map>
#include <memory>
#include <string>
#include <vector>

// ------------------------------------------------------------
// ServiceRegistry
//
// Owns a collection of named Pipeline shared pointers.
// Callers register pipelines by name and later dispatch them
// to trigger execution.
// ------------------------------------------------------------

class ServiceRegistry
{
public:

    // --------------------------------------------------------
    // Register (or replace) a pipeline under name.
    // --------------------------------------------------------
    void register_service(const std::string& name,
                          std::shared_ptr<Pipeline> pipeline);

    // --------------------------------------------------------
    // Retrieve the pipeline registered under name.
    // Returns nullptr if name is not registered.
    // --------------------------------------------------------
    std::shared_ptr<Pipeline> get_service(const std::string& name) const;

    // --------------------------------------------------------
    // Return the names of all registered services.
    // --------------------------------------------------------
    std::vector<std::string> service_names() const;

    // --------------------------------------------------------
    // Execute the pipeline registered under name.
    // No-op if name is not registered.
    // --------------------------------------------------------
    void dispatch(const std::string& name);

private:

    std::map<std::string, std::shared_ptr<Pipeline>> services_;

};  // class ServiceRegistry

#endif // FIXTURE_MIDDLEWARE_SERVICE_REGISTRY_H

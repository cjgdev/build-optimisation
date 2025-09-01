#ifndef FIXTURE_CODEGEN_PROTO_REGISTRY_H
#define FIXTURE_CODEGEN_PROTO_REGISTRY_H

// ============================================================
// proto/registry.h  --  Hand-authored proto dispatch registry
// ============================================================

#include <string>
#include <map>
#include <functional>
#include <vector>

#include "message_registry.h"

// ------------------------------------------------------------
// ProtoRegistry
//
// Maps message type names to handler callbacks.  Handlers
// receive the serialised message data and return true on
// success.  The registry owns no generated code directly;
// it delegates to MessageRegistry (generated) via registry.cpp.
// ------------------------------------------------------------

class ProtoRegistry
{
public:

    // --------------------------------------------------------
    // Register a handler for the given type name.
    // Replaces any previously registered handler for that name.
    // --------------------------------------------------------
    void register_handler(
        const std::string& type_name,
        std::function<bool(const std::string&)> handler);

    // --------------------------------------------------------
    // Dispatch a serialised message to its registered handler.
    // Returns false if no handler is registered for type_name.
    // --------------------------------------------------------
    bool dispatch(
        const std::string& type_name,
        const std::string& data) const;

    // --------------------------------------------------------
    // Returns the list of type names that have handlers.
    // --------------------------------------------------------
    std::vector<std::string> registered_handlers() const;

private:

    // Map from type name to handler function.
    std::map<std::string, std::function<bool(const std::string&)>> handlers_;

};  // class ProtoRegistry

#endif // FIXTURE_CODEGEN_PROTO_REGISTRY_H

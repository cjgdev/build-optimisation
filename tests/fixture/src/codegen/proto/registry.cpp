// ============================================================
// proto/registry.cpp  --  Implementation of ProtoRegistry
// ============================================================
//
// This file deliberately includes both the hand-authored
// proto/registry.h and the generated message_registry.h so
// that the authored layer is linked to the generated layer
// at compile time.
// ============================================================

#include "proto/registry.h"
#include "message_registry.h"

// ------------------------------------------------------------
// ProtoRegistry::register_handler()
// Stores the handler, overwriting any previous entry.
// ------------------------------------------------------------
void ProtoRegistry::register_handler(
    const std::string& type_name,
    std::function<bool(const std::string&)> handler)
{
    handlers_[type_name] = handler;
}

// ------------------------------------------------------------
// ProtoRegistry::dispatch()
// Looks up the handler for type_name and invokes it with data.
// Returns false if no handler is found.
// ------------------------------------------------------------
bool ProtoRegistry::dispatch(
    const std::string& type_name,
    const std::string& data) const
{
    auto it = handlers_.find(type_name);
    if (it == handlers_.end())
    {
        return false;
    }
    return it->second(data);
}

// ------------------------------------------------------------
// ProtoRegistry::registered_handlers()
// Returns the names of all types that have a handler.
// ------------------------------------------------------------
std::vector<std::string> ProtoRegistry::registered_handlers() const
{
    std::vector<std::string> names;
    names.reserve(handlers_.size());
    for (const auto& kv : handlers_)
    {
        names.push_back(kv.first);
    }
    return names;
}

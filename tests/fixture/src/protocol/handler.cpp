// ============================================================
// protocol/handler.cpp  --  Command handler implementation
// ============================================================

#include "protocol/handler.h"
#include "protocol/connection.h"

// ------------------------------------------------------------
// Handler::register_command
// ------------------------------------------------------------
void Handler::register_command(const std::string& command, Callback cb)
{
    commands_[command] = std::move(cb);
}

// ------------------------------------------------------------
// Handler::handle
//
// Looks up the command in the registry and invokes its
// callback with the supplied payload.  Returns an empty
// string if no handler is registered.
// ------------------------------------------------------------
std::string Handler::handle(const std::string& command, const std::string& payload) const
{
    auto it = commands_.find(command);
    if (it == commands_.end()) {
        return std::string{};
    }
    return it->second(payload);
}

// ------------------------------------------------------------
// Handler::has_command
// ------------------------------------------------------------
bool Handler::has_command(const std::string& command) const
{
    return commands_.find(command) != commands_.end();
}

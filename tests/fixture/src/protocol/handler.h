#ifndef FIXTURE_PROTOCOL_HANDLER_H
#define FIXTURE_PROTOCOL_HANDLER_H

// ============================================================
// protocol/handler.h  --  Command handler dispatcher
// ============================================================

#include <functional>
#include <map>
#include <string>

// ------------------------------------------------------------
// Handler
//
// Maintains a registry of named commands, each associated with
// a callback that accepts a payload string and returns a
// response string.  Dispatches incoming command+payload pairs
// to the appropriate callback.
// ------------------------------------------------------------

class Handler
{
public:

    // --------------------------------------------------------
    // Callback type: takes a payload, returns a response.
    // --------------------------------------------------------
    using Callback = std::function<std::string(const std::string&)>;

    // --------------------------------------------------------
    // Register a callback for the given command name.
    // Replaces any previously registered callback.
    // --------------------------------------------------------
    void register_command(const std::string& command, Callback cb);

    // --------------------------------------------------------
    // Dispatch the command with the given payload.
    // Returns the callback's response, or an empty string if
    // no callback is registered for the command.
    // --------------------------------------------------------
    std::string handle(const std::string& command, const std::string& payload) const;

    // --------------------------------------------------------
    // Returns true if a callback is registered for command.
    // --------------------------------------------------------
    bool has_command(const std::string& command) const;

private:

    std::map<std::string, Callback> commands_;

};  // class Handler

#endif // FIXTURE_PROTOCOL_HANDLER_H

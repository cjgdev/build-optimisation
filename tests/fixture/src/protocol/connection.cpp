// ============================================================
// connection.cpp  --  Simulated network connection implementation
// ============================================================
//
// Including protocol/connection.h pulls the full depth-5 chain:
//
//   protocol/connection.h
//     -> serialization/encoder.h
//       -> proto/registry.h
//         -> generated/message_registry.h  (at build time)
//           -> core/types.h
//
// ============================================================

#include "protocol/connection.h"

#include <stdexcept>
#include <sstream>

// ------------------------------------------------------------
// Connection::Connection
// ------------------------------------------------------------
Connection::Connection(const std::string& host, int port)
    : host_(host)
    , port_(port)
    , connected_(false)
{
}

// ------------------------------------------------------------
// Connection::connect
//
// Simulates establishing a TCP connection.  Always succeeds.
// ------------------------------------------------------------
bool Connection::connect()
{
    connected_ = true;
    return true;
}

// ------------------------------------------------------------
// Connection::disconnect
// ------------------------------------------------------------
void Connection::disconnect()
{
    connected_ = false;
}

// ------------------------------------------------------------
// Connection::send
//
// Encodes the message using the Encoder and returns the framed
// string that would have been transmitted.
// ------------------------------------------------------------
std::string Connection::send(const std::string& type_name, const std::string& data)
{
    if (!connected_) {
        throw std::runtime_error(
            "Connection::send: not connected to " + host_);
    }
    return encoder_.encode(type_name, data);
}

// ------------------------------------------------------------
// Connection::is_connected
// ------------------------------------------------------------
bool Connection::is_connected() const
{
    return connected_;
}

#ifndef FIXTURE_PROTOCOL_CONNECTION_H
#define FIXTURE_PROTOCOL_CONNECTION_H

// ============================================================
// protocol/connection.h  --  Simulated network connection
// ============================================================
//
// DEPTH-5 INCLUDE CHAIN PATHOLOGY
// --------------------------------
// This header intentionally includes serialization/encoder.h,
// which in turn includes proto/registry.h, creating a chain:
//
//   protocol/connection.h          (depth 1)
//     -> serialization/encoder.h   (depth 2)
//       -> proto/registry.h        (depth 3)
//         -> generated/message_registry.h  (depth 4, at build time)
//           -> core/types.h        (depth 5, via messages.h)
//
// This chain is used to exercise and measure the cost of deep
// transitive header inclusion in the build-optimisation fixture.
//
// ============================================================

#include <string>

#include "serialization/encoder.h"

// ------------------------------------------------------------
// Connection
//
// Represents a simulated connection to a remote host.
// Uses an Encoder to frame messages before "sending" them.
// No actual network I/O is performed.
// ------------------------------------------------------------

class Connection
{
public:

    // --------------------------------------------------------
    // Construct a connection to the given host:port.
    // Does not connect immediately; call connect() first.
    // --------------------------------------------------------
    explicit Connection(const std::string& host, int port);

    // --------------------------------------------------------
    // Simulate establishing the connection.
    // Returns true on success (always succeeds in simulation).
    // --------------------------------------------------------
    bool connect();

    // --------------------------------------------------------
    // Simulate closing the connection.
    // --------------------------------------------------------
    void disconnect();

    // --------------------------------------------------------
    // Encode a typed message and "send" it over the connection.
    // Returns the encoded frame that would have been sent.
    // Throws std::runtime_error if not connected.
    // --------------------------------------------------------
    std::string send(const std::string& type_name, const std::string& data);

    // --------------------------------------------------------
    // Returns true if connect() has been called and
    // disconnect() has not been called since.
    // --------------------------------------------------------
    bool is_connected() const;

private:

    std::string host_;
    int         port_;
    bool        connected_ = false;
    Encoder     encoder_;

};  // class Connection

#endif // FIXTURE_PROTOCOL_CONNECTION_H

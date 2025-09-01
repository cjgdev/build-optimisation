#ifndef FIXTURE_SERIALIZATION_ENCODER_H
#define FIXTURE_SERIALIZATION_ENCODER_H

// ============================================================
// serialization/encoder.h  --  Message encoder
// ============================================================
//
// NOTE: Including proto/registry.h here is intentional.
// It creates the depth-5 include chain pathology used for
// analysis of deep transitive header costs:
//
//   protocol/connection.h
//     -> serialization/encoder.h          (depth 2)
//       -> proto/registry.h               (depth 3)
//         -> generated/message_registry.h (depth 4, when built)
//           -> core/types.h               (depth 5, via messages.h)
//
// ============================================================

#include <string>
#include <vector>
#include <cstdint>

#include "proto/registry.h"

// ------------------------------------------------------------
// Encoder
//
// Encodes typed messages into a wire format using simple
// prefix-length framing.  Consults the ProtoRegistry to
// validate that a given type name is known before encoding.
// ------------------------------------------------------------

class Encoder
{
public:

    // --------------------------------------------------------
    // Encode a message of the given type to a framed string.
    // Format: "<type_name>\n<length>\n<data>"
    // --------------------------------------------------------
    std::string encode(const std::string& type_name, const std::string& data) const;

    // --------------------------------------------------------
    // Encode a message to a binary byte buffer.
    // Format: 4-byte big-endian type_name length, type_name
    //         bytes, 4-byte big-endian data length, data bytes.
    // --------------------------------------------------------
    std::vector<uint8_t> encode_binary(const std::string& type_name, const std::string& data) const;

    // --------------------------------------------------------
    // Returns true if the type name is a registered proto type.
    // --------------------------------------------------------
    bool supports_type(const std::string& type_name) const;

private:

    ProtoRegistry registry_;

};  // class Encoder

#endif // FIXTURE_SERIALIZATION_ENCODER_H

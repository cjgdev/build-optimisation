// ============================================================
// serialization/encoder.cpp  --  Message encoder implementation
// ============================================================
//
// Including proto/registry.h via encoder.h pulls in the full
// codegen chain.  The explicit include of "proto/registry.h"
// below (also present in the header) documents the dependency
// at the translation-unit level and is the entry point for the
// deep include chain pathology.
//
// ============================================================

#include "serialization/encoder.h"
#include "proto/registry.h"

#include <sstream>
#include <stdexcept>

// ------------------------------------------------------------
// Encoder::encode
//
// Produces a text-framed message:
//   <type_name>\n<data_length>\n<data>
// ------------------------------------------------------------
std::string Encoder::encode(const std::string& type_name, const std::string& data) const
{
    std::ostringstream oss;
    oss << type_name << '\n'
        << data.size() << '\n'
        << data;
    return oss.str();
}

// ------------------------------------------------------------
// Encoder::encode_binary
//
// Produces a binary-framed message:
//   [4-byte BE type_name length][type_name bytes]
//   [4-byte BE data length][data bytes]
// ------------------------------------------------------------
std::vector<uint8_t> Encoder::encode_binary(
    const std::string& type_name,
    const std::string& data) const
{
    std::vector<uint8_t> result;

    auto push_uint32 = [&](uint32_t v) {
        result.push_back(static_cast<uint8_t>((v >> 24) & 0xFF));
        result.push_back(static_cast<uint8_t>((v >> 16) & 0xFF));
        result.push_back(static_cast<uint8_t>((v >>  8) & 0xFF));
        result.push_back(static_cast<uint8_t>( v        & 0xFF));
    };

    push_uint32(static_cast<uint32_t>(type_name.size()));
    for (unsigned char c : type_name) {
        result.push_back(c);
    }

    push_uint32(static_cast<uint32_t>(data.size()));
    for (unsigned char c : data) {
        result.push_back(c);
    }

    return result;
}

// ------------------------------------------------------------
// Encoder::supports_type
//
// Delegates to the ProtoRegistry to check whether the given
// type name has a registered handler.
// ------------------------------------------------------------
bool Encoder::supports_type(const std::string& type_name) const
{
    const auto handlers = registry_.registered_handlers();
    for (const auto& name : handlers) {
        if (name == type_name) {
            return true;
        }
    }
    return false;
}

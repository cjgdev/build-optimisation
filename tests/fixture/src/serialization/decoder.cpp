// ============================================================
// serialization/decoder.cpp  --  Message decoder implementation
// ============================================================

#include "serialization/decoder.h"

#include <sstream>
#include <stdexcept>

// ------------------------------------------------------------
// Decoder::decode
//
// Parses the text-framed format produced by Encoder::encode:
//   <type_name>\n<data_length>\n<data>
// Returns only the data payload.
// ------------------------------------------------------------
std::string Decoder::decode(const std::string& encoded_data) const
{
    std::istringstream iss(encoded_data);

    std::string type_name;
    if (!std::getline(iss, type_name)) {
        throw std::runtime_error("Decoder::decode: missing type name");
    }

    std::string length_str;
    if (!std::getline(iss, length_str)) {
        throw std::runtime_error("Decoder::decode: missing length");
    }

    std::size_t expected_length = 0;
    try {
        expected_length = static_cast<std::size_t>(std::stoul(length_str));
    } catch (const std::exception&) {
        throw std::runtime_error("Decoder::decode: invalid length field");
    }

    std::string payload;
    payload.resize(expected_length);
    if (!iss.read(&payload[0], static_cast<std::streamsize>(expected_length))) {
        throw std::runtime_error("Decoder::decode: data truncated");
    }

    return payload;
}

// ------------------------------------------------------------
// Decoder::decode_binary
//
// Parses the binary-framed format produced by
// Encoder::encode_binary:
//   [4-byte BE type_name length][type_name bytes]
//   [4-byte BE data length][data bytes]
// Returns only the data payload.
// ------------------------------------------------------------
std::string Decoder::decode_binary(const std::vector<uint8_t>& data) const
{
    if (data.size() < 4) {
        throw std::runtime_error("Decoder::decode_binary: buffer too short for type_name length");
    }

    std::size_t offset = 0;

    auto read_uint32 = [&]() -> uint32_t {
        uint32_t v = (static_cast<uint32_t>(data[offset])     << 24)
                   | (static_cast<uint32_t>(data[offset + 1]) << 16)
                   | (static_cast<uint32_t>(data[offset + 2]) <<  8)
                   |  static_cast<uint32_t>(data[offset + 3]);
        offset += 4;
        return v;
    };

    uint32_t type_len = read_uint32();
    if (offset + type_len > data.size()) {
        throw std::runtime_error("Decoder::decode_binary: buffer too short for type_name");
    }
    offset += type_len;  // skip over the type name bytes

    if (offset + 4 > data.size()) {
        throw std::runtime_error("Decoder::decode_binary: buffer too short for data length");
    }

    uint32_t data_len = read_uint32();
    if (offset + data_len > data.size()) {
        throw std::runtime_error("Decoder::decode_binary: buffer too short for data payload");
    }

    return std::string(
        reinterpret_cast<const char*>(data.data() + offset),
        data_len);
}

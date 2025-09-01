#ifndef FIXTURE_SERIALIZATION_DECODER_H
#define FIXTURE_SERIALIZATION_DECODER_H

// ============================================================
// serialization/decoder.h  --  Message decoder
// ============================================================

#include <string>
#include <vector>
#include <cstdint>

// ------------------------------------------------------------
// Decoder
//
// Decodes messages that were encoded by Encoder.  Supports
// both the text (prefix-length framed) and binary formats.
// ------------------------------------------------------------

class Decoder
{
public:

    // --------------------------------------------------------
    // Decode a text-framed message produced by Encoder::encode.
    // Returns the raw data payload, stripping the type and
    // length prefix.  Throws std::runtime_error on malformed
    // input.
    // --------------------------------------------------------
    std::string decode(const std::string& encoded_data) const;

    // --------------------------------------------------------
    // Decode a binary-framed message produced by
    // Encoder::encode_binary.  Returns the raw data payload.
    // Throws std::runtime_error on malformed input.
    // --------------------------------------------------------
    std::string decode_binary(const std::vector<uint8_t>& data) const;

};  // class Decoder

#endif // FIXTURE_SERIALIZATION_DECODER_H

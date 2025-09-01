#ifndef FIXTURE_CORE_TYPES_H
#define FIXTURE_CORE_TYPES_H

#include <cstdint>
#include <string>

using u32  = uint32_t;
using i64  = int64_t;
using f64  = double;
using byte = uint8_t;

enum class ErrorCode {
    OK,
    INVALID_ARG,
    NOT_FOUND,
    IO_ERROR,
    TIMEOUT
};

template<typename T>
struct Result {
    T         value;
    ErrorCode error;
    bool ok() const { return error == ErrorCode::OK; }
};

std::string to_string(ErrorCode code);

#endif // FIXTURE_CORE_TYPES_H

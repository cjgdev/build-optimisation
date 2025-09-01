#include "core/types.h"

std::string to_string(ErrorCode code) {
    switch (code) {
        case ErrorCode::OK:          return "OK";
        case ErrorCode::INVALID_ARG: return "INVALID_ARG";
        case ErrorCode::NOT_FOUND:   return "NOT_FOUND";
        case ErrorCode::IO_ERROR:    return "IO_ERROR";
        case ErrorCode::TIMEOUT:     return "TIMEOUT";
        default:                     return "UNKNOWN";
    }
}

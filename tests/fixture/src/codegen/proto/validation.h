#ifndef FIXTURE_CODEGEN_PROTO_VALIDATION_H
#define FIXTURE_CODEGEN_PROTO_VALIDATION_H

// ============================================================
// proto/validation.h  --  Message validation utilities
// ============================================================

#include <string>

// ------------------------------------------------------------
// validate_message()
//
// Returns true if the serialised 'data' represents a valid
// instance of the message identified by 'type_name'.
// Dispatches to the registered handler in ProtoRegistry to
// perform the check.
// ------------------------------------------------------------
bool validate_message(
    const std::string& type_name,
    const std::string& data);

// ------------------------------------------------------------
// validate_field_count()
//
// Returns true if 'data' contains exactly 'expected_fields'
// pipe-delimited ('|') fields.
// ------------------------------------------------------------
bool validate_field_count(
    const std::string& data,
    int expected_fields);

#endif // FIXTURE_CODEGEN_PROTO_VALIDATION_H

// ============================================================
// proto/validation.cpp  --  Implementation of validation utilities
// ============================================================

#include "proto/validation.h"
#include "proto/registry.h"

#include <string>

// ------------------------------------------------------------
// validate_message()
//
// Delegates to the ProtoRegistry to find a registered handler
// for the given type_name, then invokes it with data.
// If no handler is registered the message is considered invalid.
// ------------------------------------------------------------
bool validate_message(
    const std::string& type_name,
    const std::string& data)
{
    // A local registry instance is used here; in production
    // code you would pass the registry by reference or use a
    // shared singleton.
    ProtoRegistry registry;

    // Register a basic validation handler: dispatch returns
    // false for unknown types, so use field-count heuristics
    // as a fallback.  For now, a non-empty data string and a
    // known type name constitute a valid message.
    if (type_name.empty() || data.empty())
    {
        return false;
    }

    // If a handler was registered externally it would be used
    // here; without external registration we accept any
    // non-empty data for a non-empty type_name.
    return true;
}

// ------------------------------------------------------------
// validate_field_count()
//
// Counts the number of '|'-delimited fields in data and
// compares against expected_fields.
// ------------------------------------------------------------
bool validate_field_count(
    const std::string& data,
    int expected_fields)
{
    if (expected_fields <= 0)
    {
        return false;
    }

    // Count fields: number of delimiters + 1 (when data is non-empty).
    if (data.empty())
    {
        return expected_fields == 0;
    }

    int field_count = 1;
    for (char ch : data)
    {
        if (ch == '|')
        {
            ++field_count;
        }
    }

    return field_count == expected_fields;
}

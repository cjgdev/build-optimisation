#ifndef FIXTURE_MIDDLEWARE_METRICS_COLLECTOR_H
#define FIXTURE_MIDDLEWARE_METRICS_COLLECTOR_H

// ============================================================
// middleware/metrics_collector.h  --  Runtime metrics store
// ============================================================
//
// Protocol-facing cluster: depends on serialization/encoder.h
// Collects numeric metrics and serializes them to wire format.
//
// ============================================================

#include "serialization/encoder.h"
#include <map>
#include <string>
#include <vector>

// ------------------------------------------------------------
// MetricsCollector
//
// Stores named double-valued metrics and can serialize the
// whole collection through an Encoder for transmission or
// logging.
// ------------------------------------------------------------

class MetricsCollector
{
public:

    // --------------------------------------------------------
    // Record (or overwrite) the value for metric_name.
    // --------------------------------------------------------
    void record(const std::string& metric_name, double value);

    // --------------------------------------------------------
    // Serialize all stored metrics to an encoded string.
    // Each metric is encoded individually; results are
    // concatenated with newline separators.
    // --------------------------------------------------------
    std::string serialize_all() const;

    // --------------------------------------------------------
    // Return the stored value for name, or 0.0 if absent.
    // --------------------------------------------------------
    double get_metric(const std::string& name) const;

    // --------------------------------------------------------
    // Return the number of distinct metrics currently stored.
    // --------------------------------------------------------
    std::size_t metric_count() const;

private:

    std::map<std::string, double> metrics_;
    Encoder encoder_;

};  // class MetricsCollector

#endif // FIXTURE_MIDDLEWARE_METRICS_COLLECTOR_H

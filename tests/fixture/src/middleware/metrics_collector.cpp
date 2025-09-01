#include "middleware/metrics_collector.h"

#include <sstream>
#include <string>

// ============================================================
// middleware/metrics_collector.cpp  --  MetricsCollector impl
// ============================================================
//
// Protocol-facing cluster.
// Uses Encoder to wrap each metric value in the wire format
// defined by serialization/.
//
// ============================================================

// ------------------------------------------------------------
// record
//
// Inserts or overwrites the entry for metric_name in the map.
// ------------------------------------------------------------
void MetricsCollector::record(const std::string& metric_name, double value)
{
    metrics_[metric_name] = value;
}

// ------------------------------------------------------------
// serialize_all
//
// Encodes every stored metric as "<name>=<value>" data under
// the "metric" type, then concatenates all encoded frames.
// ------------------------------------------------------------
std::string MetricsCollector::serialize_all() const
{
    std::string result;
    for (const auto& [name, value] : metrics_)
    {
        std::ostringstream data;
        data << name << "=" << value;
        result += encoder_.encode("metric", data.str());
        result += "\n";
    }
    return result;
}

// ------------------------------------------------------------
// get_metric
//
// Returns the stored value, or 0.0 if the name is not found.
// ------------------------------------------------------------
double MetricsCollector::get_metric(const std::string& name) const
{
    auto it = metrics_.find(name);
    if (it == metrics_.end())
    {
        return 0.0;
    }
    return it->second;
}

// ------------------------------------------------------------
// metric_count
// ------------------------------------------------------------
std::size_t MetricsCollector::metric_count() const
{
    return metrics_.size();
}

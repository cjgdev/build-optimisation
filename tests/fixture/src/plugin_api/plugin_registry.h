#ifndef FIXTURE_PLUGIN_API_PLUGIN_REGISTRY_H
#define FIXTURE_PLUGIN_API_PLUGIN_REGISTRY_H

#include <string>
#include <map>
#include <functional>

class PluginRegistry {
public:
    using PluginEntry = std::function<bool(const std::string&)>;

    static PluginRegistry& instance();

    bool register_plugin(const std::string& name, PluginEntry entry);
    bool has_plugin(const std::string& name) const;
    bool invoke(const std::string& name, const std::string& args) const;
    std::size_t count() const;

private:
    PluginRegistry() = default;
    std::map<std::string, PluginEntry> plugins_;
};

#endif

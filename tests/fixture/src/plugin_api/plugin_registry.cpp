#include "plugin_api/plugin_registry.h"

PluginRegistry& PluginRegistry::instance() {
    static PluginRegistry registry;
    return registry;
}

bool PluginRegistry::register_plugin(const std::string& name, PluginEntry entry) {
    auto [it, inserted] = plugins_.emplace(name, std::move(entry));
    return inserted;
}

bool PluginRegistry::has_plugin(const std::string& name) const {
    return plugins_.count(name) > 0;
}

bool PluginRegistry::invoke(const std::string& name, const std::string& args) const {
    auto it = plugins_.find(name);
    if (it == plugins_.end()) {
        return false;
    }
    return it->second(args);
}

std::size_t PluginRegistry::count() const {
    return plugins_.size();
}

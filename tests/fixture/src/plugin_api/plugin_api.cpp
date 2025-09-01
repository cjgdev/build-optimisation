#include "plugin_api/plugin_api.h"
#include "plugin_api/plugin_registry.h"
#include "core/types.h"
#include "logging/logger.h"

PluginApi::PluginApi() = default;
PluginApi::~PluginApi() = default;

bool PluginApi::load_plugin(const std::string& name, PluginEntry entry) {
    Logger::instance().info("Loading plugin: " + name);
    return PluginRegistry::instance().register_plugin(name, std::move(entry));
}

bool PluginApi::invoke_plugin(const std::string& name,
                               const std::string& args) const {
    if (!PluginRegistry::instance().has_plugin(name)) {
        Logger::instance().warn("Plugin not found: " + name);
        return false;
    }
    return PluginRegistry::instance().invoke(name, args);
}

bool PluginApi::has_plugin(const std::string& name) const {
    return PluginRegistry::instance().has_plugin(name);
}

std::size_t PluginApi::plugin_count() const {
    return PluginRegistry::instance().count();
}

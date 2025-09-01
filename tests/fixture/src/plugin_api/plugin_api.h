#ifndef FIXTURE_PLUGIN_API_PLUGIN_API_H
#define FIXTURE_PLUGIN_API_PLUGIN_API_H

#include <string>
#include <functional>

#ifdef _WIN32
#  define PLUGIN_API_EXPORT __declspec(dllexport)
#else
#  define PLUGIN_API_EXPORT __attribute__((visibility("default")))
#endif

class PLUGIN_API_EXPORT PluginApi {
public:
    using PluginEntry = std::function<bool(const std::string&)>;

    PluginApi();
    ~PluginApi();

    bool load_plugin(const std::string& name, PluginEntry entry);
    bool invoke_plugin(const std::string& name, const std::string& args) const;
    bool has_plugin(const std::string& name) const;
    std::size_t plugin_count() const;
};

#endif

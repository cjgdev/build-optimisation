#include "platform/filesystem.h"

#include <sys/stat.h>

namespace platform {

bool path_exists(const std::string& path) {
    struct stat st{};
    return stat(path.c_str(), &st) == 0;
}

std::string filename(const std::string& path) {
    const auto pos = path.rfind('/');
    if (pos == std::string::npos) {
        return path;
    }
    return path.substr(pos + 1);
}

std::string directory(const std::string& path) {
    const auto pos = path.rfind('/');
    if (pos == std::string::npos) {
        return "";
    }
    if (pos == 0) {
        return "/";
    }
    return path.substr(0, pos);
}

std::string join_paths(const std::string& a, const std::string& b) {
    if (a.empty()) return b;
    if (b.empty()) return a;
    if (a.back() == '/') {
        return a + b;
    }
    return a + '/' + b;
}

bool make_directory(const std::string& path) {
    return mkdir(path.c_str(), 0755) == 0;
}

} // namespace platform

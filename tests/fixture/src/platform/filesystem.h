#ifndef FIXTURE_PLATFORM_FILESYSTEM_H
#define FIXTURE_PLATFORM_FILESYSTEM_H

#include <string>

namespace platform {

bool path_exists(const std::string& path);
std::string filename(const std::string& path);
std::string directory(const std::string& path);
std::string join_paths(const std::string& a, const std::string& b);
bool make_directory(const std::string& path);

} // namespace platform

#endif // FIXTURE_PLATFORM_FILESYSTEM_H

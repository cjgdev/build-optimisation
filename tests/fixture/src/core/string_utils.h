#ifndef FIXTURE_CORE_STRING_UTILS_H
#define FIXTURE_CORE_STRING_UTILS_H

#include <string>
#include <vector>

std::string              trim(const std::string& s);
std::vector<std::string> split(const std::string& s, char delim);
std::string              join(const std::vector<std::string>& parts, const std::string& sep);
std::string              to_upper(const std::string& s);

#endif // FIXTURE_CORE_STRING_UTILS_H

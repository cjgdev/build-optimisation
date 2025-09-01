#ifndef FIXTURE_COMPUTE_PIPELINE_H
#define FIXTURE_COMPUTE_PIPELINE_H

#include "math/matrix.h"
#include <functional>
#include <string>
#include <utility>
#include <vector>

class Pipeline {
public:
    Pipeline() = default;

    void add_stage(const std::string& name, std::function<void()> stage);

    void execute();

    math::Matrix<float, 4, 4> transform(const math::Matrix<float, 4, 4>& input) const;

    std::size_t stage_count() const;

private:
    std::vector<std::pair<std::string, std::function<void()>>> stages_;
};

#endif // FIXTURE_COMPUTE_PIPELINE_H

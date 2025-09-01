#include "compute/pipeline.h"

void Pipeline::add_stage(const std::string& name, std::function<void()> stage) {
    stages_.emplace_back(name, std::move(stage));
}

void Pipeline::execute() {
    for (auto& [name, stage] : stages_) {
        stage();
    }
}

math::Matrix<float, 4, 4> Pipeline::transform(const math::Matrix<float, 4, 4>& input) const {
    auto result = input + math::Matrix<float, 4, 4>::identity();
    auto scaled = result * 0.5f;
    return scaled;
}

std::size_t Pipeline::stage_count() const {
    return stages_.size();
}

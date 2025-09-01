#include "compute/scheduler.h"

Scheduler::Scheduler(std::size_t num_threads)
    : pool_(num_threads) {}

void Scheduler::schedule(const std::string& task_name, std::function<void()> task) {
    pending_.emplace_back(task_name, std::move(task));
}

void Scheduler::run_all() {
    for (auto& [name, task] : pending_) {
        pool_.enqueue(std::move(task));
    }
    pending_.clear();
}

std::size_t Scheduler::pending_count() const {
    return pending_.size();
}

#ifndef FIXTURE_COMPUTE_SCHEDULER_H
#define FIXTURE_COMPUTE_SCHEDULER_H

#include "platform/thread_pool.h"
#include <functional>
#include <string>
#include <utility>
#include <vector>

class Scheduler {
public:
    explicit Scheduler(std::size_t num_threads);

    void schedule(const std::string& task_name, std::function<void()> task);

    void run_all();

    std::size_t pending_count() const;

private:
    platform::ThreadPool pool_;
    std::vector<std::pair<std::string, std::function<void()>>> pending_;
};

#endif // FIXTURE_COMPUTE_SCHEDULER_H

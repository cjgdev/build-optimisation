#include "math/matrix.h"
#include "compute/pipeline.h"
#include <iostream>
#include <cmath>

extern void report(const char* name, bool passed);

void test_compute_suite() {
    std::cout << "Compute tests:" << std::endl;

    {
        auto id = math::Matrix<float,3,3>::identity();
        report("matrix_identity_diag", id(0,0) == 1.0f && id(1,1) == 1.0f && id(2,2) == 1.0f);
    }

    {
        auto id = math::Matrix<float,3,3>::identity();
        auto det = id.determinant();
        report("matrix_determinant", std::abs(det - 1.0f) < 1e-6f);
    }

    {
        math::Matrix<float,2,3> a;
        a(0,0) = 1; a(0,1) = 2; a(0,2) = 3;
        a(1,0) = 4; a(1,1) = 5; a(1,2) = 6;
        auto t = a.transpose();
        report("matrix_transpose", t(0,0) == 1.0f && t(2,1) == 6.0f);
    }

    {
        Pipeline pipeline;
        bool executed = false;
        pipeline.add_stage("test", [&executed]() { executed = true; });
        report("pipeline_add_stage", pipeline.stage_count() == 1);
        pipeline.execute();
        report("pipeline_execute", executed);
    }
}

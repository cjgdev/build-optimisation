#ifndef FIXTURE_MATH_TRANSFORMS_H
#define FIXTURE_MATH_TRANSFORMS_H

#include "math/matrix.h"
#include "math/vector.h"
#include <cmath>

namespace math {

// 2D rotation matrix (3x3 homogeneous)
template<typename T>
Matrix<T, 3, 3> rotation_2d(T angle) {
    T c = std::cos(angle);
    T s = std::sin(angle);
    return Matrix<T, 3, 3>{
        c,  -s,  T{0},
        s,   c,  T{0},
        T{0}, T{0}, T{1}
    };
}

// Diagonal scaling matrix NxN
template<typename T, std::size_t N>
Matrix<T, N, N> scale(const Vector<T, N>& factors) {
    Matrix<T, N, N> result = Matrix<T, N, N>::zero();
    for (std::size_t i = 0; i < N; ++i)
        result(i, i) = factors[i];
    return result;
}

// 3D translation (4x4 homogeneous)
template<typename T>
Matrix<T, 4, 4> translate_3d(const Vector<T, 3>& offset) {
    Matrix<T, 4, 4> result = Matrix<T, 4, 4>::identity();
    result(0, 3) = offset[0];
    result(1, 3) = offset[1];
    result(2, 3) = offset[2];
    return result;
}

// Perspective projection (4x4)
template<typename T>
Matrix<T, 4, 4> perspective(T fov, T aspect, T near_plane, T far_plane) {
    T tan_half = std::tan(fov / T{2});
    Matrix<T, 4, 4> result = Matrix<T, 4, 4>::zero();
    result(0, 0) = T{1} / (aspect * tan_half);
    result(1, 1) = T{1} / tan_half;
    result(2, 2) = -(far_plane + near_plane) / (far_plane - near_plane);
    result(2, 3) = -(T{2} * far_plane * near_plane) / (far_plane - near_plane);
    result(3, 2) = T{-1};
    return result;
}

// Look-at view matrix (4x4)
template<typename T>
Matrix<T, 4, 4> look_at(const Vector<T, 3>& eye,
                         const Vector<T, 3>& center,
                         const Vector<T, 3>& up) {
    Vector<T, 3> f = (center - eye).normalized();
    Vector<T, 3> r = cross(f, up).normalized();
    Vector<T, 3> u = cross(r, f);

    Matrix<T, 4, 4> result = Matrix<T, 4, 4>::identity();
    result(0, 0) =  r[0]; result(0, 1) =  r[1]; result(0, 2) =  r[2];
    result(1, 0) =  u[0]; result(1, 1) =  u[1]; result(1, 2) =  u[2];
    result(2, 0) = -f[0]; result(2, 1) = -f[1]; result(2, 2) = -f[2];
    result(0, 3) = -r.dot(eye);
    result(1, 3) = -u.dot(eye);
    result(2, 3) =  f.dot(eye);
    return result;
}

} // namespace math

#endif // FIXTURE_MATH_TRANSFORMS_H

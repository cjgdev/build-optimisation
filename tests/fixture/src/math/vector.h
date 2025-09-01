#ifndef FIXTURE_MATH_VECTOR_H
#define FIXTURE_MATH_VECTOR_H

#include "math/matrix.h"
#include <cmath>

namespace math {

template<typename T, std::size_t N>
class Vector {
public:
    Vector() : data_() {}

    Vector(std::initializer_list<T> init) {
        std::size_t i = 0;
        for (T val : init) {
            if (i >= N) break;
            data_(i++, 0) = val;
        }
    }

    explicit Vector(const Matrix<T, N, 1>& m) : data_(m) {}

    T& operator[](std::size_t i) {
        return data_(i, 0);
    }

    const T& operator[](std::size_t i) const {
        return data_(i, 0);
    }

    T dot(const Vector& other) const {
        T result = T{};
        for (std::size_t i = 0; i < N; ++i)
            result += (*this)[i] * other[i];
        return result;
    }

    T length() const {
        return std::sqrt(dot(*this));
    }

    Vector normalized() const {
        T len = length();
        Vector result;
        for (std::size_t i = 0; i < N; ++i)
            result[i] = (*this)[i] / len;
        return result;
    }

    Vector operator+(const Vector& other) const {
        Vector result;
        for (std::size_t i = 0; i < N; ++i)
            result[i] = (*this)[i] + other[i];
        return result;
    }

    Vector operator-(const Vector& other) const {
        Vector result;
        for (std::size_t i = 0; i < N; ++i)
            result[i] = (*this)[i] - other[i];
        return result;
    }

    Vector operator*(T scalar) const {
        Vector result;
        for (std::size_t i = 0; i < N; ++i)
            result[i] = (*this)[i] * scalar;
        return result;
    }

    const Matrix<T, N, 1>& as_matrix() const { return data_; }

private:
    Matrix<T, N, 1> data_;
};

// 3D cross product as a free function
template<typename T>
Vector<T, 3> cross(const Vector<T, 3>& a, const Vector<T, 3>& b) {
    return Vector<T, 3>{
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0]
    };
}

} // namespace math

#endif // FIXTURE_MATH_VECTOR_H

#ifndef FIXTURE_MATH_MATRIX_H
#define FIXTURE_MATH_MATRIX_H

#include <array>
#include <stdexcept>
#include <type_traits>
#include <cmath>
#include <algorithm>
#include <ostream>
#include <numeric>

namespace math {

template<typename T, std::size_t Rows, std::size_t Cols>
class Matrix {
public:
    static constexpr std::size_t rows = Rows;
    static constexpr std::size_t cols = Cols;

    // Constructors
    Matrix() : data_{} {}

    explicit Matrix(T fill_value) {
        data_.fill(fill_value);
    }

    Matrix(std::initializer_list<T> init) {
        std::size_t i = 0;
        for (T val : init) {
            if (i >= Rows * Cols) break;
            data_[i++] = val;
        }
    }

    // Element access with bounds checking
    T& operator()(std::size_t r, std::size_t c) {
        if (r >= Rows || c >= Cols)
            throw std::out_of_range("Matrix index out of range");
        return data_[r * Cols + c];
    }

    const T& operator()(std::size_t r, std::size_t c) const {
        if (r >= Rows || c >= Cols)
            throw std::out_of_range("Matrix index out of range");
        return data_[r * Cols + c];
    }

    T& at(std::size_t r, std::size_t c) {
        return (*this)(r, c);
    }

    const T& at(std::size_t r, std::size_t c) const {
        return (*this)(r, c);
    }

    const T* data() const { return data_.data(); }
    T*       data()       { return data_.data(); }

    // Element-wise arithmetic (return new Matrix)
    Matrix operator+(const Matrix& other) const {
        Matrix result;
        for (std::size_t i = 0; i < Rows * Cols; ++i)
            result.data_[i] = data_[i] + other.data_[i];
        return result;
    }

    Matrix operator-(const Matrix& other) const {
        Matrix result;
        for (std::size_t i = 0; i < Rows * Cols; ++i)
            result.data_[i] = data_[i] - other.data_[i];
        return result;
    }

    Matrix operator*(T scalar) const {
        Matrix result;
        for (std::size_t i = 0; i < Rows * Cols; ++i)
            result.data_[i] = data_[i] * scalar;
        return result;
    }

    Matrix operator/(T scalar) const {
        Matrix result;
        for (std::size_t i = 0; i < Rows * Cols; ++i)
            result.data_[i] = data_[i] / scalar;
        return result;
    }

    // Compound assignment
    Matrix& operator+=(const Matrix& other) {
        for (std::size_t i = 0; i < Rows * Cols; ++i)
            data_[i] += other.data_[i];
        return *this;
    }

    Matrix& operator-=(const Matrix& other) {
        for (std::size_t i = 0; i < Rows * Cols; ++i)
            data_[i] -= other.data_[i];
        return *this;
    }

    Matrix& operator*=(T scalar) {
        for (std::size_t i = 0; i < Rows * Cols; ++i)
            data_[i] *= scalar;
        return *this;
    }

    Matrix& operator/=(T scalar) {
        for (std::size_t i = 0; i < Rows * Cols; ++i)
            data_[i] /= scalar;
        return *this;
    }

    // Matrix multiplication
    template<std::size_t OtherCols>
    Matrix<T, Rows, OtherCols> multiply(const Matrix<T, Cols, OtherCols>& other) const {
        Matrix<T, Rows, OtherCols> result(T{0});
        for (std::size_t r = 0; r < Rows; ++r) {
            for (std::size_t c = 0; c < OtherCols; ++c) {
                for (std::size_t k = 0; k < Cols; ++k) {
                    result(r, c) += (*this)(r, k) * other(k, c);
                }
            }
        }
        return result;
    }

    // Transpose
    Matrix<T, Cols, Rows> transpose() const {
        Matrix<T, Cols, Rows> result;
        for (std::size_t r = 0; r < Rows; ++r)
            for (std::size_t c = 0; c < Cols; ++c)
                result(c, r) = (*this)(r, c);
        return result;
    }

    // Determinant — 1x1 base case
    template<std::size_t N = Rows>
    typename std::enable_if<(N == 1 && Rows == Cols), T>::type
    determinant() const {
        return data_[0];
    }

    // Determinant — 2x2 base case
    template<std::size_t N = Rows>
    typename std::enable_if<(N == 2 && Rows == Cols), T>::type
    determinant() const {
        return data_[0] * data_[3] - data_[1] * data_[2];
    }

    // Determinant — NxN recursive Laplace expansion
    template<std::size_t N = Rows>
    typename std::enable_if<(N > 2 && Rows == Cols), T>::type
    determinant() const {
        T det = T{};
        for (std::size_t j = 0; j < Cols; ++j) {
            Matrix<T, Rows - 1, Cols - 1> minor;
            for (std::size_t r = 1; r < Rows; ++r) {
                std::size_t col = 0;
                for (std::size_t c = 0; c < Cols; ++c) {
                    if (c == j) continue;
                    minor(r - 1, col++) = (*this)(r, c);
                }
            }
            T sign = (j % 2 == 0) ? T{1} : T{-1};
            det += sign * data_[j] * minor.determinant();
        }
        return det;
    }

    // Trace (square matrices only)
    template<std::size_t N = Rows>
    typename std::enable_if<(N == Rows && Rows == Cols), T>::type
    trace() const {
        T sum = T{};
        for (std::size_t i = 0; i < Rows; ++i)
            sum += data_[i * Cols + i];
        return sum;
    }

    // Equality
    bool operator==(const Matrix& other) const {
        return data_ == other.data_;
    }

    bool operator!=(const Matrix& other) const {
        return !(*this == other);
    }

    // Stream output
    friend std::ostream& operator<<(std::ostream& os, const Matrix& m) {
        for (std::size_t r = 0; r < Rows; ++r) {
            os << "[ ";
            for (std::size_t c = 0; c < Cols; ++c) {
                os << m(r, c);
                if (c + 1 < Cols) os << ", ";
            }
            os << " ]";
            if (r + 1 < Rows) os << "\n";
        }
        return os;
    }

    // Static factories (square matrices only)
    template<std::size_t N = Rows>
    static typename std::enable_if<(N == Rows && Rows == Cols), Matrix>::type
    identity() {
        Matrix m;
        for (std::size_t i = 0; i < Rows; ++i)
            m(i, i) = T{1};
        return m;
    }

    static Matrix zero() {
        return Matrix(T{0});
    }

private:
    std::array<T, Rows * Cols> data_;
};

} // namespace math

#endif // FIXTURE_MATH_MATRIX_H

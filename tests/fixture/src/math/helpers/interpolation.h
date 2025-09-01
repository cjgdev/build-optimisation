#ifndef FIXTURE_MATH_HELPERS_INTERPOLATION_H
#define FIXTURE_MATH_HELPERS_INTERPOLATION_H

namespace math {

template<typename T>
T lerp(T a, T b, T t);

template<typename T>
T bilinear(T q00, T q10, T q01, T q11, T tx, T ty);

template<typename T>
T smoothstep(T edge0, T edge1, T x);

} // namespace math

#endif // FIXTURE_MATH_HELPERS_INTERPOLATION_H

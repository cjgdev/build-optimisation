#include "math/helpers/interpolation.h"

namespace math {

template<typename T>
T lerp(T a, T b, T t) {
    return a + t * (b - a);
}

template<typename T>
T bilinear(T q00, T q10, T q01, T q11, T tx, T ty) {
    T top    = lerp(q00, q10, tx);
    T bottom = lerp(q01, q11, tx);
    return lerp(top, bottom, ty);
}

template<typename T>
T smoothstep(T edge0, T edge1, T x) {
    T t = (x - edge0) / (edge1 - edge0);
    if (t < T{0}) t = T{0};
    if (t > T{1}) t = T{1};
    return t * t * (T{3} - T{2} * t);
}

// Explicit instantiations
template float  lerp<float> (float,  float,  float);
template double lerp<double>(double, double, double);

template float  bilinear<float> (float,  float,  float,  float,  float,  float);
template double bilinear<double>(double, double, double, double, double, double);

template float  smoothstep<float> (float,  float,  float);
template double smoothstep<double>(double, double, double);

} // namespace math

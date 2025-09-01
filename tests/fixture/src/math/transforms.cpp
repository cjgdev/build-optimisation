#include "math/transforms.h"

// Explicit instantiations for rotation_2d
template math::Matrix<float,  3, 3> math::rotation_2d<float> (float);
template math::Matrix<double, 3, 3> math::rotation_2d<double>(double);

// Explicit instantiations for scale (float, sizes 2..8)
template math::Matrix<float, 2, 2> math::scale<float, 2>(const math::Vector<float, 2>&);
template math::Matrix<float, 3, 3> math::scale<float, 3>(const math::Vector<float, 3>&);
template math::Matrix<float, 4, 4> math::scale<float, 4>(const math::Vector<float, 4>&);
template math::Matrix<float, 5, 5> math::scale<float, 5>(const math::Vector<float, 5>&);
template math::Matrix<float, 6, 6> math::scale<float, 6>(const math::Vector<float, 6>&);
template math::Matrix<float, 7, 7> math::scale<float, 7>(const math::Vector<float, 7>&);
template math::Matrix<float, 8, 8> math::scale<float, 8>(const math::Vector<float, 8>&);

// Explicit instantiations for scale (double, sizes 2..8)
template math::Matrix<double, 2, 2> math::scale<double, 2>(const math::Vector<double, 2>&);
template math::Matrix<double, 3, 3> math::scale<double, 3>(const math::Vector<double, 3>&);
template math::Matrix<double, 4, 4> math::scale<double, 4>(const math::Vector<double, 4>&);
template math::Matrix<double, 5, 5> math::scale<double, 5>(const math::Vector<double, 5>&);
template math::Matrix<double, 6, 6> math::scale<double, 6>(const math::Vector<double, 6>&);
template math::Matrix<double, 7, 7> math::scale<double, 7>(const math::Vector<double, 7>&);
template math::Matrix<double, 8, 8> math::scale<double, 8>(const math::Vector<double, 8>&);

// Explicit instantiations for translate_3d
template math::Matrix<float,  4, 4> math::translate_3d<float> (const math::Vector<float,  3>&);
template math::Matrix<double, 4, 4> math::translate_3d<double>(const math::Vector<double, 3>&);

// Explicit instantiations for perspective
template math::Matrix<float,  4, 4> math::perspective<float> (float,  float,  float,  float);
template math::Matrix<double, 4, 4> math::perspective<double>(double, double, double, double);

// Explicit instantiations for look_at
template math::Matrix<float,  4, 4> math::look_at<float> (const math::Vector<float,  3>&, const math::Vector<float,  3>&, const math::Vector<float,  3>&);
template math::Matrix<double, 4, 4> math::look_at<double>(const math::Vector<double, 3>&, const math::Vector<double, 3>&, const math::Vector<double, 3>&);

// Force additional template instantiation work — drives recursive determinant
// for square sizes 2..8 for both float and double.
namespace {

template<typename T, std::size_t N>
void force_instantiate() {
    math::Matrix<T, N, N> m = math::Matrix<T, N, N>::identity();
    auto det = m.determinant();
    auto tr  = m.transpose();
    auto m2  = m + m;
    auto m3  = m * T{2};
    (void)det; (void)tr; (void)m2; (void)m3;
}

template void force_instantiate<float,  2>();
template void force_instantiate<float,  3>();
template void force_instantiate<float,  4>();
template void force_instantiate<float,  5>();
template void force_instantiate<float,  6>();
template void force_instantiate<float,  7>();
template void force_instantiate<float,  8>();

template void force_instantiate<double, 2>();
template void force_instantiate<double, 3>();
template void force_instantiate<double, 4>();
template void force_instantiate<double, 5>();
template void force_instantiate<double, 6>();
template void force_instantiate<double, 7>();
template void force_instantiate<double, 8>();

} // anonymous namespace

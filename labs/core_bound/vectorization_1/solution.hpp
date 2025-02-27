#include <array>  // std::array
#include <utility> // std::pair
#include <vector>  // std::vector

inline constexpr size_t sequence_size_v = 200; // The length of the generated sequences.
inline constexpr size_t sequence_count_v = 16; // The number of sequences to generate for both sequence collections.

using sequence_t = std::array<uint8_t, sequence_size_v>;
using result_t = std::array<int16_t, sequence_count_v>;

result_t compute_alignment(std::vector<sequence_t> const &, std::vector<sequence_t> const &);
std::pair<std::vector<sequence_t>, std::vector<sequence_t>> init();

// Clang-12 compiler generates branches for std::max, which are often mispredicted
// in this benchmark. That's the reason we provide branchless version of max function.
template <typename T>
inline T max(T a, T b) {
	return a - ((a-b) & (a-b)>>31);
}

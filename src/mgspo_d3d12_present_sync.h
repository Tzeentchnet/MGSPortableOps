#ifndef MGSPO_D3D12_PRESENT_SYNC_H
#define MGSPO_D3D12_PRESENT_SYNC_H

#include <cstddef>
#include <cstdint>

struct MgspoD3D12PresentSyncResult {
    bool success;
    bool blocked;
    std::size_t readbacks;
};

template <typename Target, typename Overlaps, typename Current, typename Readback>
MgspoD3D12PresentSyncResult mgspo_sync_framebuffers_for_cpu_present(
    Target *targets, std::size_t count, uint32_t address, uint32_t bytes,
    Overlaps overlaps, Current current, Readback readback) {
    if (!bytes) return {true, false, 0};
    for (std::size_t i = 0; i < count; ++i) {
        Target *target = &targets[i];
        if (
            target->occupied &&
            target->gpu_newer &&
            current(target) &&
            overlaps(&target->key, address, bytes))
            return {true, true, 0};
    }

    std::size_t readbacks = 0;
    for (std::size_t i = 0; i < count; ++i) {
        Target *target = &targets[i];
        if (
            target->occupied &&
            target->gpu_newer &&
            overlaps(&target->key, address, bytes)) {
            if (!readback(target))
                return {false, false, readbacks};
            ++readbacks;
        }
    }
    return {true, false, readbacks};
}

#endif

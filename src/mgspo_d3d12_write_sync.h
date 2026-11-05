#ifndef MGSPO_D3D12_WRITE_SYNC_H
#define MGSPO_D3D12_WRITE_SYNC_H

#include <cstddef>
#include <cstdint>

template <typename Target, typename Overlaps, typename Readback>
bool mgspo_sync_framebuffers_before_write(
    Target *targets, std::size_t count, uint32_t address, uint32_t bytes,
    Overlaps overlaps, Readback readback) {
    if (!bytes) return true;
    for (std::size_t i = 0; i < count; ++i) {
        Target *target = &targets[i];
        if (
            target->occupied &&
            target->gpu_newer &&
            overlaps(&target->key, address, bytes) &&
            !readback(target))
            return false;
    }
    return true;
}

#endif

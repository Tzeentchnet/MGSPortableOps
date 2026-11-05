#include "../../../src/mgspo_d3d12_write_sync.h"
#include "../../../src/mgspo_d3d12_present_sync.h"

#include <array>
#include <cstdio>

struct FakeKey {
    uint32_t address;
    uint32_t bytes;
};

struct FakeTarget {
    FakeKey key;
    bool occupied;
    bool gpu_newer;
    uint64_t capture_generation;
    bool used_current;
    bool transitioned_current;
    bool fail;
    unsigned reads;
    std::array<uint8_t, 16> cpu;
    std::array<uint8_t, 16> gpu;
};

static bool overlaps(const FakeKey *key, uint32_t address, uint32_t bytes) {
    return uint64_t(address) < uint64_t(key->address) + key->bytes &&
           uint64_t(key->address) < uint64_t(address) + bytes;
}

static bool readback(FakeTarget *target) {
    ++target->reads;
    if (target->fail) return false;
    target->cpu = target->gpu;
    target->gpu_newer = false;
    return true;
}

static bool check(bool condition, const char *message) {
    if (!condition) fprintf(stderr, "FAIL: %s\n", message);
    return condition;
}

int main() {
    FakeTarget targets[4] = {};
    for (unsigned i = 0; i < 4; ++i) {
        targets[i].key = {0x04000000u + i * 0x100u, 16u};
        targets[i].occupied = true;
        targets[i].gpu_newer = true;
        for (unsigned j = 0; j < targets[i].gpu.size(); ++j)
            targets[i].gpu[j] = static_cast<uint8_t>(j + 1u);
    }
    targets[2].key.address = targets[0].key.address;
    targets[2].occupied = false;
    targets[3].key.address = targets[0].key.address;
    targets[3].gpu_newer = false;

    if (!check(
            mgspo_sync_framebuffers_before_write(
                targets, 4, 0x04000006u, 1u, overlaps, readback),
            "overlapping write synchronization failed"))
        return 1;
    if (!check(
            targets[0].reads == 1 && targets[1].reads == 0 &&
            targets[2].reads == 0 && targets[3].reads == 0,
            "only occupied, newer, overlapping targets should be read back"))
        return 1;
    targets[0].cpu[6] = 0xfeu;
    for (unsigned i = 0; i < targets[0].cpu.size(); ++i) {
        uint8_t expected = i == 6 ? 0xfeu : targets[0].gpu[i];
        if (!check(targets[0].cpu[i] == expected, "unwritten pixels changed"))
            return 1;
    }

    targets[0].gpu_newer = true;
    targets[0].fail = true;
    if (!check(
            !mgspo_sync_framebuffers_before_write(
                targets, 4, 0x04000006u, 1u, overlaps, readback),
            "readback failure was not surfaced"))
        return 1;
    if (!check(
            mgspo_sync_framebuffers_before_write(
                targets, 4, 0x04000006u, 0u, overlaps, readback),
            "empty write should not trigger a readback"))
        return 1;
    if (!check(targets[0].reads == 2, "empty write performed a readback"))
        return 1;

    for (FakeTarget &target : targets) {
        target.fail = false;
        target.reads = 0;
        target.gpu_newer = false;
    }
    targets[0].gpu_newer = true;
    targets[0].capture_generation = 8;
    targets[0].used_current = true;
    targets[1].gpu_newer = true;
    targets[1].capture_generation = 8;
    MgspoD3D12PresentSyncResult present =
        mgspo_sync_framebuffers_for_cpu_present(
            targets, 4, 0x04000000u, 0x200u, overlaps,
            [](FakeTarget *target) {
                return
                    target->capture_generation == 9 ||
                    target->transitioned_current;
            },
            readback);
    if (!check(
            present.success && !present.blocked && present.readbacks == 2,
            "prior-generation presentation targets were not synchronized"))
        return 1;
    if (!check(
            targets[0].reads == 1 && targets[1].reads == 1,
            "presentation synchronization did not read each overlap once"))
        return 1;

    targets[0].gpu_newer = true;
    targets[0].capture_generation = 8;
    targets[0].used_current = false;
    targets[0].transitioned_current = true;
    targets[1].gpu_newer = true;
    targets[1].capture_generation = 8;
    targets[0].reads = targets[1].reads = 0;
    present = mgspo_sync_framebuffers_for_cpu_present(
        targets, 4, 0x04000000u, 0x200u, overlaps,
        [](FakeTarget *target) {
            return
                target->capture_generation == 9 ||
                target->transitioned_current;
        },
        readback);
    if (!check(
            present.success && present.blocked && present.readbacks == 0,
            "current-generation work did not block presentation batching"))
        return 1;
    if (!check(
            targets[0].reads == 0 && targets[1].reads == 0,
            "blocked presentation synchronization performed a readback"))
        return 1;

    targets[0].transitioned_current = false;
    targets[0].capture_generation = 9;
    present = mgspo_sync_framebuffers_for_cpu_present(
        targets, 4, 0x04000000u, 0x200u, overlaps,
        [](FakeTarget *target) {
            return
                target->capture_generation == 9 ||
                target->transitioned_current;
        },
        readback);
    if (!check(
            present.success && present.blocked && present.readbacks == 0,
            "current-generation render target did not block batching"))
        return 1;

    targets[0].gpu_newer = false;
    targets[0].capture_generation = 8;
    targets[0].used_current = false;
    targets[0].transitioned_current = false;
    targets[1].gpu_newer = true;
    targets[1].fail = true;
    present = mgspo_sync_framebuffers_for_cpu_present(
        targets, 4, 0x04000000u, 0x200u, overlaps,
        [](FakeTarget *target) {
            return
                target->capture_generation == 9 ||
                target->transitioned_current;
        },
        readback);
    if (!check(
            !present.success && !present.blocked && present.readbacks == 0,
            "presentation readback failure was not surfaced"))
        return 1;

    puts(
        "OK: CPU writes and presentation fallback preserve newer "
        "GPU framebuffers");
    return 0;
}

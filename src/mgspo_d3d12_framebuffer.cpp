#define ged3d12_framebuffer_read mgspo_d3d12_framebuffer_read_pinned
#define ged3d12_framebuffer_present_source \
    mgspo_d3d12_framebuffer_present_source_pinned
#define ged3d12_framebuffer_bind mgspo_d3d12_framebuffer_bind_pinned
#define ged3d12_framebuffer_bind_destination \
    mgspo_d3d12_framebuffer_bind_destination_pinned
#define ged3d12_framebuffer_texture_bind \
    mgspo_d3d12_framebuffer_texture_bind_pinned
#include "gpu_d3d12/framebuffer.cpp"
#undef ged3d12_framebuffer_texture_bind
#undef ged3d12_framebuffer_bind_destination
#undef ged3d12_framebuffer_bind
#undef ged3d12_framebuffer_present_source
#undef ged3d12_framebuffer_read
#include "mgspo_d3d12_present_sync.h"
#include "mgspo_d3d12_write_sync.h"

#include <cstdlib>
#include <cstring>

static constexpr uint32_t MGSPO_D3D12_PRESENT_WIDTH = 480u;
static constexpr uint32_t MGSPO_D3D12_PRESENT_HEIGHT = 272u;

struct MgspoD3D12CpuPresent {
    uint32_t address;
    uint32_t bytes;
    uint32_t bytes_per_pixel;
    bool pending;
};

struct MgspoD3D12ReadBurst {
    uint32_t base;
    uint32_t bytes_per_pixel;
    uint32_t stride;
    uint32_t calls;
};

static MgspoD3D12CpuPresent s_mgspo_cpu_present;
static MgspoD3D12ReadBurst s_mgspo_read_burst;
static uint64_t s_mgspo_target_use_generation[MAX_TARGETS];
static uint64_t s_mgspo_target_transition_generation[MAX_TARGETS];

static bool mgspo_d3d12_batch_present_reads(void) {
    static int enabled = -1;
    if (enabled < 0) {
        const char *setting =
            std::getenv("MGSPO_D3D12_BATCH_PRESENT_READBACK");
        if (!setting || !setting[0] || std::strcmp(setting, "1") == 0) {
            enabled = 1;
        } else if (std::strcmp(setting, "0") == 0) {
            enabled = 0;
        } else {
            fprintf(
                stderr,
                "MGSPO_D3D12_BATCH_PRESENT_READBACK: expected 0 or 1, got %s\n",
                setting);
            std::exit(2);
        }
    }
    return enabled != 0;
}

static bool mgspo_d3d12_trace_reads(void) {
    static int enabled = -1;
    if (enabled < 0) {
        const char *setting = std::getenv("MGSPO_D3D12_READ_TRACE");
        enabled = setting && std::strcmp(setting, "1") == 0 ? 1 : 0;
    }
    return enabled != 0;
}

static void mgspo_d3d12_begin_read_burst(
    uint32_t address, uint32_t bytes) {
    s_mgspo_read_burst = {
        SR_PHYS(address),
        bytes,
        0,
        1,
    };
}

static void mgspo_d3d12_log_read_burst(void) {
    const uint64_t span =
        ((uint64_t)(MGSPO_D3D12_PRESENT_HEIGHT - 1) *
             s_mgspo_read_burst.stride +
         MGSPO_D3D12_PRESENT_WIDTH) *
        s_mgspo_read_burst.bytes_per_pixel;
    fprintf(
        stderr,
        "mgspo: D3D12 CPU-present read burst base=0x%08x bpp=%u "
        "stride=%u calls=%u generation=%llu\n",
        s_mgspo_read_burst.base,
        s_mgspo_read_burst.bytes_per_pixel,
        s_mgspo_read_burst.stride,
        s_mgspo_read_burst.calls,
        (unsigned long long)s_capture_generation);
    for (uint32_t i = 0; i < MAX_TARGETS; ++i) {
        ColorTarget *target = &s_targets[i];
        if (
            !target->occupied ||
            !ged3d12_framebuffer_key_overlaps(
                &target->key, s_mgspo_read_burst.base, (uint32_t)span))
            continue;
        fprintf(
            stderr,
            "mgspo: D3D12 CPU-present target=%u address=0x%08x "
            "stride=%u format=%u gpu_newer=%u pending_upload=%u "
            "generation=%llu captured_current=%u used_current=%u "
            "transitioned_current=%u active=%u\n",
            i,
            target->key.address,
            target->key.stride,
            target->key.format,
            target->gpu_newer ? 1u : 0u,
            target->pending_upload ? 1u : 0u,
            (unsigned long long)target->capture_generation,
            target->capture_generation == s_capture_generation ? 1u : 0u,
            s_mgspo_target_use_generation[i] == s_capture_generation
                ? 1u
                : 0u,
            s_mgspo_target_transition_generation[i] ==
                    s_capture_generation
                ? 1u
                : 0u,
            target == s_active_target ? 1u : 0u);
    }
}

static void mgspo_d3d12_trace_read(uint32_t address, uint32_t bytes) {
    if (!mgspo_d3d12_trace_reads()) return;
    address = SR_PHYS(address);
    if (bytes != 2u && bytes != 4u) {
        s_mgspo_read_burst = {};
        return;
    }
    if (
        !s_mgspo_read_burst.calls ||
        s_mgspo_read_burst.bytes_per_pixel != bytes) {
        mgspo_d3d12_begin_read_burst(address, bytes);
        return;
    }

    uint32_t index = s_mgspo_read_burst.calls;
    uint64_t expected;
    if (index < MGSPO_D3D12_PRESENT_WIDTH) {
        expected =
            (uint64_t)s_mgspo_read_burst.base + (uint64_t)index * bytes;
    } else if (index == MGSPO_D3D12_PRESENT_WIDTH) {
        uint32_t delta = address - s_mgspo_read_burst.base;
        if (delta % bytes != 0u) {
            mgspo_d3d12_begin_read_burst(address, bytes);
            return;
        }
        s_mgspo_read_burst.stride = delta / bytes;
        if (
            s_mgspo_read_burst.stride < MGSPO_D3D12_PRESENT_WIDTH ||
            s_mgspo_read_burst.stride > 2048u) {
            mgspo_d3d12_begin_read_burst(address, bytes);
            return;
        }
        expected = address;
    } else {
        expected =
            (uint64_t)s_mgspo_read_burst.base +
            ((uint64_t)(index / MGSPO_D3D12_PRESENT_WIDTH) *
                 s_mgspo_read_burst.stride +
             index % MGSPO_D3D12_PRESENT_WIDTH) *
                bytes;
    }
    if (address != expected) {
        mgspo_d3d12_begin_read_burst(address, bytes);
        return;
    }

    s_mgspo_read_burst.calls++;
    if (
        s_mgspo_read_burst.calls ==
        MGSPO_D3D12_PRESENT_WIDTH + 1u)
        mgspo_d3d12_log_read_burst();
    if (
        s_mgspo_read_burst.calls ==
        MGSPO_D3D12_PRESENT_WIDTH * MGSPO_D3D12_PRESENT_HEIGHT) {
        fprintf(
            stderr,
            "mgspo: D3D12 CPU-present read burst complete calls=%u\n",
            s_mgspo_read_burst.calls);
        s_mgspo_read_burst = {};
    }
}

static void mgspo_d3d12_mark_target_used(uint32_t handle) {
    ColorTarget *target = color_from_handle(handle);
    if (!target) return;
    s_mgspo_target_use_generation[target - s_targets] =
        s_capture_generation;
}

bool ged3d12_framebuffer_bind(
    const GeD3D12FramebufferBinding *binding) {
    bool bound = mgspo_d3d12_framebuffer_bind_pinned(binding);
    if (bound) mgspo_d3d12_mark_target_used(binding->color_handle);
    return bound;
}

bool ged3d12_framebuffer_bind_destination(
    const GeD3D12FramebufferBinding *binding) {
    bool bound =
        mgspo_d3d12_framebuffer_bind_destination_pinned(binding);
    if (bound) mgspo_d3d12_mark_target_used(binding->color_handle);
    return bound;
}

bool ged3d12_framebuffer_texture_bind(
    const GeD3D12FramebufferAlias *alias,
    const GeD3D12UploadSlice *clut,
    D3D12_GPU_DESCRIPTOR_HANDLE *descriptors) {
    ColorTarget *target =
        alias ? color_from_handle(alias->handle) : nullptr;
    D3D12_RESOURCE_STATES previous_state =
        target ? target->state : D3D12_RESOURCE_STATE_COMMON;
    bool bound = mgspo_d3d12_framebuffer_texture_bind_pinned(
        alias, clut, descriptors);
    if (target && target->state != previous_state) {
        s_mgspo_target_transition_generation[target - s_targets] =
            s_capture_generation;
    }
    if (bound) mgspo_d3d12_mark_target_used(alias->handle);
    return bound;
}

bool ged3d12_framebuffer_present_source(
    uint32_t address, uint32_t format, uint32_t stride,
    D3D12_TEXTURE_COPY_LOCATION *source, D3D12_BOX *source_box) {
    bool cached = mgspo_d3d12_framebuffer_present_source_pinned(
        address, format, stride, source, source_box);
    s_mgspo_cpu_present = {};
    if (!cached) {
        uint32_t normalized_stride = stride & 0x7ffu;
        if (!normalized_stride)
            normalized_stride = GE_D3D12_FRAMEBUFFER_WIDTH;
        uint32_t bytes_per_pixel = (format & 3u) == 3u ? 4u : 2u;
        uint64_t bytes =
            ((uint64_t)(MGSPO_D3D12_PRESENT_HEIGHT - 1u) *
                 normalized_stride +
             MGSPO_D3D12_PRESENT_WIDTH) *
            bytes_per_pixel;
        if (bytes <= UINT32_MAX) {
            s_mgspo_cpu_present = {
                0x04000000u | (address & 0x001fffffu),
                (uint32_t)bytes,
                bytes_per_pixel,
                true,
            };
        }
    }
    return cached;
}

static void mgspo_d3d12_prepare_cpu_present_read(
    uint32_t address, uint32_t bytes) {
    if (!s_mgspo_cpu_present.pending) return;
    MgspoD3D12CpuPresent present = s_mgspo_cpu_present;
    s_mgspo_cpu_present = {};
    if (
        SR_PHYS(address) != present.address ||
        bytes != present.bytes_per_pixel ||
        !mgspo_d3d12_batch_present_reads())
        return;

    MgspoD3D12PresentSyncResult result =
        mgspo_sync_framebuffers_for_cpu_present(
            s_targets, MAX_TARGETS, present.address, present.bytes,
            ged3d12_framebuffer_key_overlaps,
            [](ColorTarget *target) {
                uint32_t index = (uint32_t)(target - s_targets);
                return
                    target->capture_generation == s_capture_generation ||
                    s_mgspo_target_transition_generation[index] ==
                        s_capture_generation;
            },
            readback_color);
    if (!result.success) {
        fprintf(
            stderr,
            "mgspo: D3D12 CPU-present framebuffer synchronization failed "
            "at 0x%08x (%u bytes)\n",
            present.address, present.bytes);
        std::exit(2);
    }
    if (result.blocked) {
        fprintf(
            stderr,
            "mgspo: D3D12 CPU-present batching skipped for "
            "current-generation GPU work\n");
    } else if (result.readbacks) {
        fprintf(
            stderr,
            "mgspo: D3D12 batched CPU-present readback targets=%zu "
            "address=0x%08x bytes=%u\n",
            result.readbacks, present.address, present.bytes);
    }
}

void ged3d12_framebuffer_read(uint32_t address, uint32_t bytes) {
    mgspo_d3d12_prepare_cpu_present_read(address, bytes);
    mgspo_d3d12_trace_read(address, bytes);
    mgspo_d3d12_framebuffer_read_pinned(address, bytes);
}

static void mgspo_d3d12_prepare_write(uint32_t address, uint32_t bytes) {
    if (!s_initialized) {
        fprintf(stderr, "mgspo: D3D12 framebuffer write before initialization\n");
        std::exit(2);
    }
    /* A partial readback leaves the rest GPU-newer before whole-target invalidation. */
    if (!mgspo_sync_framebuffers_before_write(
            s_targets, MAX_TARGETS, address, bytes,
            ged3d12_framebuffer_key_overlaps, readback_color)) {
        fprintf(
            stderr,
            "mgspo: D3D12 framebuffer write synchronization failed "
            "at 0x%08x (%u bytes)\n",
            address, bytes);
        std::exit(2);
    }
}

extern "C" int mgspo_d3d12_install_write_coherency(void) {
    const GeBackend *backend = ge_backend_get();
    if (!backend) return 1;
    if (
        !s_initialized ||
        !backend->name ||
        strcmp(backend->name, "d3d12") != 0 ||
        !backend->vram_read ||
        !backend->vram_write) {
        fprintf(stderr, "mgspo: cannot install D3D12 framebuffer write synchronization\n");
        return 0;
    }

    static GeBackend synchronized_backend;
    synchronized_backend = *backend;
    synchronized_backend.vram_write = mgspo_d3d12_prepare_write;
    ge_set_backend(&synchronized_backend);
    fprintf(stderr, "mgspo: D3D12 framebuffer write synchronization enabled\n");
    return 1;
}

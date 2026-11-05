#include "mgspo_log.h"

#include <limits.h>

#define sr_hle_register sr_hle_register_builtin
#define sr_syscall_lib sr_mgspo_syscall_lib_builtin
#define sr_vblank_tick sr_mgspo_vblank_tick_builtin
#include "../external/psp-recomp/src/rt/hle.c"
#undef sr_vblank_tick
#undef sr_syscall_lib
#undef sr_hle_register

int mgspo_module_identity_active(const char *identity);
uint32_t mgspo_module_uid_active(const char *identity);
int mgspo_kjfs_probe_run(CpuState *state, const char *path);
int mgspo_kjfs_probe_observe_syscall(
    const char *name, uint32_t nid, uint32_t pc,
    uint32_t thread_uid, const uint32_t arguments[4],
    uint32_t result);
uint32_t sr_module_stop(
    uint32_t uid,
    uint32_t argument_size,
    uint32_t argument_address,
    uint32_t status_address,
    uint32_t option_address);

static int mgspo_pause_menu_visible(void) {
    const SrDisplayFramebuffer *framebuffer =
        sr_display_state_get_framebuffer(&s_display, 0);
    if (
        !framebuffer ||
        !framebuffer->address ||
        framebuffer->format != 1 ||
        !framebuffer->stride)
        return 0;
    /* Synchronize once before inspecting the framebuffer pixel by pixel. */
    if (g_sr_gpu_vram_read_watch)
        sr_gpu_vram_read(UINT32_C(0x04000000), UINT32_C(0x00200000));
    uint32_t red_pixels = 0;
    for (uint32_t y = 0; y < 272; ++y) {
        for (uint32_t x = 0; x < 240; ++x) {
            uint16_t pixel = MEM_R16(
                framebuffer->address +
                (y * framebuffer->stride + x) * 2u);
            uint32_t red = pixel & 0x1fu;
            uint32_t green = (pixel >> 5) & 0x1fu;
            uint32_t blue = (pixel >> 10) & 0x1fu;
            if (red >= 20u && green <= 7u && blue <= 7u)
                red_pixels++;
        }
    }
    return red_pixels >= 1000u;
}

static int mgspo_pause_menu_capture_phase(void) {
    static const uint32_t anchors[][2] = {
        {8u, 108u},
        {120u, 115u},
        {230u, 122u},
    };
    const SrDisplayFramebuffer *framebuffer =
        sr_display_state_get_framebuffer(&s_display, 0);
    if (
        !framebuffer ||
        !framebuffer->address ||
        framebuffer->format != 1 ||
        !framebuffer->stride)
        return 0;

    /* Stabilize the globally animated red highlight before exact capture. */
    for (size_t index = 0; index < _countof(anchors); ++index) {
        uint32_t x = anchors[index][0];
        uint32_t y = anchors[index][1];
        uint16_t pixel = MEM_R16(
            framebuffer->address +
            (y * framebuffer->stride + x) * 2u);
        if ((pixel & 0x7fffu) != 0x0439u)
            return 0;
    }
    return 1;
}

void sr_vblank_tick(void) {
    static int route_enabled = -1;
    static uint32_t flash_start_vblank;
    static uint32_t pause_start_vblank;
    static uint32_t pause_visible_vblank;
    static int pause_started;
    static int mission_activation_logged;
    sr_mgspo_vblank_tick_builtin();

    if (route_enabled < 0) {
        const char *setting = getenv("MGSPO_AUTOMATE_FIRST_MISSION");
        route_enabled =
            setting && strcmp(setting, "1") == 0
            ? 1
            : 0;
        if (setting && setting[0] &&
            strcmp(setting, "0") != 0 &&
            strcmp(setting, "1") != 0) {
            fprintf(
                stderr,
                "MGSPO_AUTOMATE_FIRST_MISSION: expected 0 or 1, got %s\n",
                setting);
            _Exit(2);
        }
    }
    if (!route_enabled) return;

    if (
        !mission_activation_logged &&
        mgspo_module_identity_active(
            "disc0:/sce_lbn0x68110_size0x10c724")) {
        mission_activation_logged = 1;
        fprintf(
            stderr,
            "first-mission automation: mission active at "
            "present=%u vblank=%u\n",
            s_present_count, s_vcount);
    }

    int sample = (s_ctrl_w + CTRL_RING - 1) % CTRL_RING;
    int advance_overlay =
        mgspo_module_identity_active(
            "disc0:/sce_lbn0x710d0_size0x498bc") ||
        mgspo_module_identity_active(
            "disc0:/sce_lbn0x776a0_size0xc3c") ||
        mgspo_module_identity_active(
            "disc0:/sce_lbn0x58270_size0x34d84") ||
        mgspo_module_identity_active(
            "disc0:/sce_lbn0x6a2e0_size0xc4c");
    if (s_present_count >= 5700 && advance_overlay) {
        if (!flash_start_vblank) flash_start_vblank = s_vcount;
        uint32_t phase = (s_vcount - flash_start_vblank) % 30u;
        if (phase < 3u)
            s_ctrl_ring[sample].btn |= 0x0008u;
        else if (phase >= 10u && phase < 13u)
            s_ctrl_ring[sample].btn |= 0x2000u;
    }

    if (
        s_present_count >= 7000 &&
        mgspo_module_identity_active(
            "disc0:/sce_lbn0x68110_size0x10c724")) {
        if (mgspo_pause_menu_visible()) {
            if (!pause_visible_vblank) {
                pause_visible_vblank = s_vcount;
                fprintf(
                    stderr,
                    "first-mission automation: pause visible at "
                    "present=%u vblank=%u\n",
                    s_present_count, s_vcount);
            }
            if (
                s_vcount - pause_visible_vblank >= 10u &&
                mgspo_pause_menu_capture_phase()) {
                const char *capture =
                    getenv("MGSPO_FIRST_MISSION_CAPTURE");
                const SrDisplayFramebuffer *framebuffer =
                    sr_display_state_get_framebuffer(&s_display, 0);
                if (
                    !capture ||
                    !capture[0] ||
                    !framebuffer ||
                    !framebuffer->address ||
                    dump_fb_fmt(
                        capture,
                        framebuffer->address,
                        (int)framebuffer->format,
                        framebuffer->stride) != 0) {
                    fprintf(
                        stderr,
                        "first-mission automation: cannot capture "
                        "stable pause checkpoint\n");
                    runtime_exit_cleanly(2);
                }
                fprintf(
                    stderr,
                    "first-mission pause checkpoint reached at "
                    "present=%u vblank=%u\n",
                    s_present_count, s_vcount);
                runtime_exit_cleanly(0);
            }
            return;
        }
        pause_visible_vblank = 0;
        if (!pause_started) {
            pause_started = 1;
            pause_start_vblank = s_vcount;
            fprintf(
                stderr,
                "first-mission automation: pause at present=%u vblank=%u\n",
                s_present_count, s_vcount);
        }
        if ((s_vcount - pause_start_vblank) % 30u < 3u)
            s_ctrl_ring[sample].btn |= 0x0008u;
    }
}

uint32_t mgspo_sched_change_current_attr(
    uint32_t clear_attributes, uint32_t set_attributes);
uint32_t mgspo_sched_release_wait_thread(uint32_t uid);
int mgspo_sched_consume_wait_release(void);

void sr_syscall_lib(CpuState *state, const char *library, uint32_t nid) {
    uint32_t arguments[4] = {
        state->r[4], state->r[5], state->r[6], state->r[7],
    };
    uint32_t thread_uid = sched_current_uid();
    uint32_t pc = state->pc;
    HleEntry *entry = hle_find(nid);
    const char *name =
        entry && entry->name ? entry->name : sr_nid_name(nid);
    if (!name) name = "unknown";

    mgspo_log_syscall(
        "dispatch",
        library,
        name,
        nid,
        thread_uid,
        pc,
        arguments,
        0);

    if (!entry) {
        uint32_t target;
        const char *resolved_library;
        if (!sr_module_find_export(
                library, nid, &target, &resolved_library)) {
            mgspo_log_fatal(
                "unimplemented_import",
                name,
                nid,
                pc);
        }
    }

    sr_mgspo_syscall_lib_builtin(state, library, nid);

    mgspo_log_syscall(
        "return",
        library,
        name,
        nid,
        thread_uid,
        pc,
        arguments,
        state->r[2]);
    int block_observation = mgspo_kjfs_probe_observe_syscall(
        name, nid, pc, thread_uid, arguments, state->r[2]);
    if (block_observation)
        runtime_exit_cleanly(block_observation > 0 ? 0 : 2);
    if (strncmp(name, "sceIo", 5) == 0 && (int32_t)state->r[2] < 0)
        mgspo_log_file_failure(name, "", state->r[2]);
    if (strncmp(name, "sceGeList", 9) == 0)
        mgspo_log_display_list(
            name, thread_uid, arguments, state->r[2]);
    if (library && strcmp(library, "kjfs") == 0 &&
        nid == UINT32_C(0xc5183abb)) {
        const char *probe_output = getenv("MGSPO_KJFS_PROBE_OUTPUT");
        if (probe_output) {
            if (!probe_output[0]) {
                fprintf(stderr, "KJFS probe: output path is empty\n");
                runtime_exit_cleanly(2);
            }
            int ok = mgspo_kjfs_probe_run(state, probe_output);
            runtime_exit_cleanly(ok ? 0 : 2);
        }
    }
}

void sr_hle_register(uint32_t nid, const char *name, HleFn function) {
    HleEntry *existing = hle_find(nid);
    if (existing) {
        existing->name = name;
        existing->fn = function;
        return;
    }
    sr_hle_register_builtin(nid, name, function);
}

static uint32_t h_mgspo_set_compiled_sdk_version(CpuState *state) {
    uint32_t result = h_SetCompiledSdkVersion(state);
    s_skip_deadbeef = 1;
    return result;
}

static uint32_t h_mgspo_wait_sema(CpuState *state) {
    uint32_t uid = state->r[4];
    int need = (int)state->r[5];
    uint32_t timeout_address = state->r[6];
    Sync *semaphore = sync_find(uid);
    if (!semaphore) return UINT32_C(0x80020199);

    while (semaphore->count < need) {
        if (timeout_address) {
            uint32_t timeout = MEM_R32(timeout_address);
            int timed_out = sched_block_on_timeout(uid, timeout);
            if (mgspo_sched_consume_wait_release())
                return UINT32_C(0x800201aa);
            if (timed_out) return UINT32_C(0x800201a8);
        } else {
            sched_block_on(uid);
            if (mgspo_sched_consume_wait_release())
                return UINT32_C(0x800201aa);
        }
        semaphore = sync_find(uid);
        if (!semaphore) return UINT32_C(0x80020199);
    }
    semaphore->count -= need;
    return 0;
}

static uint32_t h_mgspo_wait_sema_cb(CpuState *state) {
    return with_callbacks(state, h_mgspo_wait_sema);
}

static uint32_t h_mgspo_signal_sema(CpuState *state) {
    uint32_t result = h_SignalSema(state);
    return result == UINT32_C(0x80020000)
        ? UINT32_C(0x80020199)
        : result;
}

static uint32_t h_mgspo_poll_sema(CpuState *state) {
    uint32_t result = h_PollSema(state);
    return result == UINT32_C(0x80020000)
        ? UINT32_C(0x80020199)
        : result;
}

static uint32_t h_mgspo_delete_sema(CpuState *state) {
    if (!sync_find(state->r[4])) return UINT32_C(0x80020199);
    return h_DeleteSema(state);
}

static uint32_t h_mgspo_change_current_thread_attr(CpuState *state) {
    return mgspo_sched_change_current_attr(state->r[4], state->r[5]);
}

static uint32_t h_mgspo_release_wait_thread(CpuState *state) {
    uint32_t result =
        mgspo_sched_release_wait_thread(state->r[4]);
    if (!result) sched_preempt();
    return result;
}

static uint64_t mgspo_rtc_tick(void) {
    return RTC_MAGIC_OFFSET +
        (uint64_t)MGSPO_RTC_UNIX_EPOCH * UINT64_C(1000000) +
        now_usec();
}

static uint32_t h_mgspo_rtc_get_current_tick(CpuState *state) {
    uint64_t tick = mgspo_rtc_tick();
    uint32_t output = state->r[4];
    if (output) {
        MEM_W32(output, (uint32_t)tick);
        MEM_W32(output + 4, (uint32_t)(tick >> 32));
    }
    return 0;
}

static uint32_t h_mgspo_rtc_get_accumulative_time(CpuState *state) {
    uint64_t tick = mgspo_rtc_tick();
    state->r[3] = (uint32_t)(tick >> 32);
    return (uint32_t)tick;
}

static uint8_t mgspo_font_snapshot_pixel(
    const uint8_t *snapshot,
    uint32_t format,
    int bytes_per_line,
    int x,
    int y) {
    static const int pixel_bytes[5] = {0, 0, 1, 3, 4};
    int size = pixel_bytes[format];
    size_t offset =
        (size_t)y * (size_t)bytes_per_line +
        (size_t)(size ? x * size : x / 2);
    uint8_t value = snapshot[offset];
    if (format <= 1) {
        int high_nibble = (x & 1) != (int)format;
        value = high_nibble ? value >> 4 : value & 0x0f;
        value = (uint8_t)(value | (value << 4));
    }
    return value;
}

static uint32_t h_mgspo_font_get_char_glyph_image_clip(CpuState *state) {
    uint32_t glyph = state->r[6];
    if (!glyph || !sr_inrange(glyph) || !sr_inrange(glyph + 23))
        return UINT32_C(0x80460001);

    uint32_t format = MEM_R32(glyph);
    int width = MEM_R16(glyph + 12);
    int height = MEM_R16(glyph + 14);
    int bytes_per_line = MEM_R16(glyph + 16);
    uint32_t buffer = MEM_R32(glyph + 20);
    if (format > 4 || width <= 0 || height <= 0 || bytes_per_line <= 0)
        return UINT32_C(0x80460001);

    size_t bytes = (size_t)bytes_per_line * (size_t)height;
    if (bytes > 64u * 1024u * 1024u ||
        buffer > UINT32_MAX - ((uint32_t)bytes - 1) ||
        !sr_inrange(buffer) ||
        !sr_inrange(buffer + (uint32_t)bytes - 1))
        return UINT32_C(0x80460001);
    uint8_t *original = (uint8_t *)malloc(bytes * 2);
    if (!original) return UINT32_C(0x80020190);
    uint8_t *rendered = original + bytes;
    memcpy(original, SR_HOST(buffer), bytes);

    uint32_t result = h_FontGetCharGlyphImage(state);
    memcpy(rendered, SR_HOST(buffer), bytes);
    memcpy(SR_HOST(buffer), original, bytes);

    int clip_x = (int32_t)state->r[7];
    int clip_y = (int32_t)stack_arg(state, 0);
    int clip_width = (int32_t)stack_arg(state, 1);
    int clip_height = (int32_t)stack_arg(state, 2);
    int start_x = clip_x < 0 ? 0 : clip_x;
    int start_y = clip_y < 0 ? 0 : clip_y;
    int end_x = clip_width > 0 && clip_x <= INT_MAX - clip_width
        ? clip_x + clip_width
        : clip_x;
    int end_y = clip_height > 0 && clip_y <= INT_MAX - clip_height
        ? clip_y + clip_height
        : clip_y;
    if (end_x > width) end_x = width;
    if (end_y > height) end_y = height;

    for (int y = start_y; y < end_y; ++y)
        for (int x = start_x; x < end_x; ++x)
            font_write_pixel(
                buffer,
                format,
                bytes_per_line,
                width,
                height,
                x,
                y,
                mgspo_font_snapshot_pixel(
                    rendered, format, bytes_per_line, x, y));
    free(original);
    return result;
}

static int s_mgspo_atrac_context_types[8];
static int s_mgspo_atrac_reconfigured;

static uint32_t h_mgspo_atrac_reinit(CpuState *state) {
    for (int index = 0; index < 8; ++index)
        if (s_atrac[index].used) return UINT32_C(0x80000021);

    memset(
        s_mgspo_atrac_context_types,
        0,
        sizeof(s_mgspo_atrac_context_types));
    int32_t at3_count = (int32_t)state->r[4];
    int32_t plus_count = (int32_t)state->r[5];
    int next = 0;
    int64_t space = 6;

    for (int32_t index = 0; index < plus_count; ++index) {
        space -= 2;
        if (space >= 0 && next < 8)
            s_mgspo_atrac_context_types[next++] = ATRAC_CODEC_PLUS;
    }
    for (int32_t index = 0; index < at3_count; ++index) {
        space -= 1;
        if (space >= 0 && next < 8)
            s_mgspo_atrac_context_types[next++] = ATRAC_CODEC_AT3;
    }
    s_mgspo_atrac_reconfigured = 1;
    return space >= 0 ? 0 : UINT32_C(0x80020190);
}

static uint32_t h_mgspo_atrac_set_data_and_get_id(CpuState *state) {
    Atrac pending;
    memset(&pending, 0, sizeof(pending));
    pending.used = 1;
    pending.buf = state->r[4];
    pending.size = state->r[5];
    pending.loopStart = pending.loopEnd = -1;

    uint32_t result = atrac_parse_riff(&pending);
    if (!result &&
        (pending.fileSize > pending.size ||
         pending.dataBytes > pending.size - pending.dataOffset)) {
        pending.streamed = 1;
        pending.ringRead = pending.dataOffset;
        pending.ringWrite = 0;
        pending.buffered = pending.size - pending.dataOffset;
        pending.fileReadOffset = pending.size;
        pending.frameOffset = pending.ringRead;
    }
    if (!result) result = atrac_prepare_decoder(&pending, 0);
    if (result) {
        atrac_destroy_decoder(&pending);
        return result;
    }

    int id = -1;
    for (int index = 0; index < 8; ++index) {
        if (s_atrac[index].used) continue;
        if (!s_mgspo_atrac_reconfigured ||
            s_mgspo_atrac_context_types[index] == pending.codec) {
            id = index;
            break;
        }
    }
    if (id < 0) {
        atrac_destroy_decoder(&pending);
        return UINT32_C(0x80630003);
    }

    s_atrac[id] = pending;
    if (atrac_log())
        fprintf(
            stderr,
            "ATRAC: set id=%d codec=0x%x channels=%d frame=%d "
            "buffer=0x%08x bytes=%u data=%u/%u samples=%d "
            "loop=%d..%d%s\n",
            id,
            pending.codec,
            pending.channels,
            pending.blockAlign,
            pending.buf,
            pending.size,
            pending.dataOffset,
            pending.dataBytes,
            pending.endSample,
            pending.loopStart,
            pending.loopEnd,
            pending.streamed ? " streamed" : "");
    return (uint32_t)id;
}

static uint32_t h_mgspo_atrac_get_max_sample(CpuState *state) {
    Atrac *atrac = atrac_of(state->r[4]);
    if (!atrac) return UINT32_C(0x80630002);
    uint32_t output = state->r[5];
    if (output && output <= UINT32_MAX - 3 &&
        sr_inrange(output) && sr_inrange(output + 3)) {
        MEM_W32(
            output,
            atrac->codec == ATRAC_CODEC_PLUS
                ? ATRAC_SAMPLES_PER_FRAME
                : ATRAC3_SAMPLES_PER_FRAME);
    }
    return 0;
}

static CpuState s_mgspo_idle_state;
static int s_mgspo_idle_state_ready;
int g_mgspo_module_start_pending;

static void mgspo_init_idle_state(void) {
    if (s_mgspo_idle_state_ready) return;
    memset(&s_mgspo_idle_state, 0, sizeof(s_mgspo_idle_state));
    for (int index = 1; index < 32; ++index)
        s_mgspo_idle_state.r[index] = UINT32_C(0xdeadbeef);
    for (int index = 0; index < 32; ++index)
        s_mgspo_idle_state.fi[index] = UINT32_C(0x7f800001);
    for (int index = 0; index < 128; ++index)
        s_mgspo_idle_state.vi[index] = UINT32_C(0x7f800001);
    s_mgspo_idle_state.r[26] = UINT32_C(0x083fff00);
    s_mgspo_idle_state.r[28] = MGSPO_MODULE_GP;
    s_mgspo_idle_state.r[29] = UINT32_C(0x083fff00);
    s_mgspo_idle_state.r[31] = UINT32_C(0x08000010);
    s_mgspo_idle_state.hi = UINT32_C(0xdeadbeef);
    s_mgspo_idle_state.lo = UINT32_C(0xdeadbeef);
    s_mgspo_idle_state.fcr31 = UINT32_C(0x00000e00);
    s_mgspo_idle_state.vfpuCtrl[0] = UINT32_C(0x000000e4);
    s_mgspo_idle_state.vfpuCtrl[1] = UINT32_C(0x000000e4);
    s_mgspo_idle_state.vfpuCtrl[3] = UINT32_C(0x0000003f);
    s_mgspo_idle_state.vfpuCtrl[7] = UINT32_C(0x7772ceab);
    s_mgspo_idle_state.vfpuCtrl[8] = UINT32_C(0x3f800001);
    s_mgspo_idle_state.vfpuCtrl[9] = UINT32_C(0x3f800002);
    s_mgspo_idle_state.vfpuCtrl[10] = UINT32_C(0x3f800004);
    s_mgspo_idle_state.vfpuCtrl[11] = UINT32_C(0x3f800008);
    for (int index = 12; index < 16; ++index)
        s_mgspo_idle_state.vfpuCtrl[index] = UINT32_C(0x3f800000);
    s_mgspo_idle_state_ready = 1;
}

static void mgspo_trace_idle_delay(
    CpuState *state, uint32_t iterations, uint32_t result) {
    mgspo_init_idle_state();
    sr_end(&s_mgspo_idle_state, 0, 0);

    for (uint32_t iteration = 0; iteration < iterations; ++iteration) {
        sr_begin(
            &s_mgspo_idle_state,
            UINT32_C(0x08000000),
            UINT32_C(0x3c1f0800));
        s_mgspo_idle_state.r[31] = UINT32_C(0x08000000);
        sr_end(&s_mgspo_idle_state, 0, 0);

        sr_begin(
            &s_mgspo_idle_state,
            UINT32_C(0x08000004),
            UINT32_C(0x03e00008));
        sr_end(&s_mgspo_idle_state, 0, 0);

        sr_begin(
            &s_mgspo_idle_state,
            UINT32_C(0x08000008),
            UINT32_C(0x010c014c));
        if (iteration + 1 == iterations) {
            CpuState resumed = *state;
            resumed.r[1] = UINT32_C(0xdeadbeef);
            resumed.r[2] = result;
            resumed.r[3] = 0;
            for (int index = 4; index <= 15; ++index)
                resumed.r[index] = UINT32_C(0xdeadbeef);
            resumed.r[24] = UINT32_C(0xdeadbeef);
            resumed.r[25] = UINT32_C(0xdeadbeef);
            resumed.hi = UINT32_C(0xdeadbeef);
            resumed.lo = UINT32_C(0xdeadbeef);
            sr_end(&resumed, 0, 0);
        } else {
            sr_end(&s_mgspo_idle_state, 0, 0);
        }
    }
}

static uint32_t h_mgspo_load_av_module(CpuState *state) {
    static const uint32_t idle_iterations[] = {22, 24, 23, 24};
    static const uint32_t allocation_sizes[] = {0, 0, 0x8000, 0xc000};
    static int loaded[4];
    uint32_t module = state->r[4];
    if (module < sizeof(idle_iterations) / sizeof(idle_iterations[0])) {
        if (!loaded[module] && allocation_sizes[module]) {
            uint32_t size = allocation_sizes[module];
            uint32_t address = sr_ba_alloc(
                sr_kmem_user(), &size, 0, "UtilityModule/av");
            if (address == SR_BA_FAIL)
                return UINT32_C(0x80020190);
        }
        loaded[module] = 1;
        mgspo_trace_idle_delay(state, idle_iterations[module], 0);
    }
    sched_delay_current(25000);
    state->r[3] = 0;
    return 0;
}

static uint32_t h_mgspo_start_module(CpuState *state) {
    uint32_t uid = state->r[4];
    g_mgspo_module_start_pending = 1;
    uint32_t result = h_StartModule(state);
    g_mgspo_module_start_pending = 0;

    static int stop_probe = -1;
    if (stop_probe < 0) {
        const char *setting =
            getenv("MGSPO_VERIFY_PLAINTEXT_STOPS");
        stop_probe =
            setting && strcmp(setting, "1") == 0
            ? 1
            : 0;
        if (setting && setting[0] &&
            strcmp(setting, "0") != 0 &&
            strcmp(setting, "1") != 0) {
            fprintf(
                stderr,
                "MGSPO_VERIFY_PLAINTEXT_STOPS: expected 0 or 1, "
                "got %s\n",
                setting);
            runtime_exit_cleanly(2);
        }
    }
    uint32_t kjfs_uid = mgspo_module_uid_active("KCEJ_FS");
    if (stop_probe && uid == kjfs_uid && result == kjfs_uid) {
        static const char *identities[] = {
            "KCEJ_FS",
            "KCEJ_SOUND2",
            "ZLIB",
        };
        for (size_t index = 0;
             index < sizeof(identities) / sizeof(identities[0]);
             ++index) {
            uint32_t module_uid =
                mgspo_module_uid_active(identities[index]);
            if (!module_uid) {
                fprintf(
                    stderr,
                    "plaintext module stop probe: %s is inactive\n",
                    identities[index]);
                runtime_exit_cleanly(2);
            }
            g_mgspo_module_start_pending = 1;
            uint32_t stop_result =
                sr_module_stop(module_uid, 0, 0, 0, 0);
            g_mgspo_module_start_pending = 0;
            if (stop_result != 0) {
                fprintf(
                    stderr,
                    "plaintext module stop probe: %s failed "
                    "with 0x%08x\n",
                    identities[index],
                    stop_result);
                runtime_exit_cleanly(2);
            }
        }
        fprintf(
            stderr,
            "plaintext module stop checkpoint reached\n");
        runtime_exit_cleanly(0);
    }
    return result;
}

static uint32_t h_mgspo_stop_module(CpuState *state) {
    g_mgspo_module_start_pending = 1;
    uint32_t result = sr_module_stop(
        state->r[4],
        state->r[5],
        state->r[6],
        state->r[7],
        state->r[8]);
    g_mgspo_module_start_pending = 0;
    return result;
}

#define MGSPO_UMD_SECTOR_SIZE UINT32_C(2048)

_Static_assert(
    SR_EXPECTED_ISO_SIZE <= UINT32_MAX,
    "UMD handles require the supported ISO size to fit in 32 bits");
_Static_assert(
    SR_EXPECTED_ISO_SIZE % MGSPO_UMD_SECTOR_SIZE == 0,
    "the supported ISO must contain complete 2048-byte sectors");

static const char *mgspo_umd_remainder(const char *path) {
    if (_strnicmp(path, "umd0:", 5) == 0) return path + 5;
    if (_strnicmp(path, "umd1:", 5) == 0) return path + 5;
    if (_strnicmp(path, "umd:", 4) == 0) return path + 4;
    return NULL;
}

static int mgspo_is_umd_path(const char *path) {
    return mgspo_umd_remainder(path) != NULL;
}

static int mgspo_is_whole_umd_path(const char *path) {
    const char *remainder = mgspo_umd_remainder(path);
    if (!remainder) return 0;
    while (*remainder == '/' || *remainder == '\\') remainder++;
    return *remainder == '\0';
}

static int mgspo_fd_is_block_sector(uint32_t fd) {
    return
        fd < 64 &&
        s_fds[fd].used &&
        mgspo_is_whole_umd_path(s_fds[fd].path);
}

enum {
    MGSPO_IO_ACCESS_READ = 1,
    MGSPO_IO_ACCESS_WRITE = 2,
};

static uint8_t s_mgspo_io_access[64];

static void mgspo_io_record_access(uint32_t fd, uint32_t flags) {
    if (fd < 64 && s_fds[fd].used)
        s_mgspo_io_access[fd] = (uint8_t)(
            flags & (MGSPO_IO_ACCESS_READ | MGSPO_IO_ACCESS_WRITE));
}

static uint32_t mgspo_io_open_umd(
    CpuState *state, const char *path) {
    int slot = io_find_slot();
    if (slot < 0) return UINT32_C(0x80010018);

    uint32_t flags = state->r[5];
    int writing = (flags & UINT32_C(0x0002)) != 0;
    int creating = (flags & UINT32_C(0x0200)) != 0;
    if (writing || creating) return UINT32_C(0x8001001e);

    uint32_t lba = 0;
    uint32_t size = 0;
    if (mgspo_is_whole_umd_path(path)) {
        if (iso_init() != 0) return UINT32_C(0x80010002);
        size = (uint32_t)SR_EXPECTED_ISO_SIZE;
    } else if (iso_lookup(path, &lba, &size) != 0) {
        fprintf(stderr, "sceIoOpen: not found: %s\n", path);
        return UINT32_C(0x80010002);
    }

    Fd *file = &s_fds[slot];
    memset(file, 0, sizeof(*file));
    file->used = 1;
    file->uid = sr_alloc_uid();
    file->lba = lba;
    file->size = size;
    file->async_priority = s_async_default_priority;
    snprintf(file->path, sizeof(file->path), "%s", path);
    return (uint32_t)slot;
}

static uint32_t mgspo_io_open_core(
    CpuState *state, const char *path) {
    uint32_t result = mgspo_is_umd_path(path)
        ? mgspo_io_open_umd(state, path)
        : h_IoOpen(state);
    if ((int32_t)result >= 0)
        mgspo_io_record_access(result, state->r[5]);
    return result;
}

static uint32_t mgspo_block_read(
    uint32_t fd, uint32_t destination, uint32_t sectors) {
    if (!mgspo_fd_is_block_sector(fd))
        return SCE_KERNEL_ERROR_BADF;
    Fd *file = &s_fds[fd];
    if (file->off % MGSPO_UMD_SECTOR_SIZE != 0)
        return UINT32_C(0x80010005);

    uint32_t remaining =
        (file->size - file->off) / MGSPO_UMD_SECTOR_SIZE;
    if (sectors > remaining) sectors = remaining;
    uint32_t bytes = sectors * MGSPO_UMD_SECTOR_SIZE;
    if (!io_guest_span(destination, bytes))
        return UINT32_C(0x80010016);
    uint32_t result = io_read(fd, destination, bytes);
    if ((int32_t)result < 0) return result;
    return result / MGSPO_UMD_SECTOR_SIZE;
}

static uint32_t mgspo_byte_read(
    uint32_t fd, uint32_t destination, uint32_t count) {
    Fd *file = &s_fds[fd];
    if (file->off >= file->size) return 0;
    uint32_t remaining = file->size - file->off;
    if (count > remaining) count = remaining;
    return io_read(fd, destination, count);
}

static int64_t mgspo_byte_seek(
    Fd *file, int64_t offset, uint32_t whence) {
    if (file->host) return io_seek(file, offset, whence);
    if (whence > 2)
        return (int64_t)(int32_t)UINT32_C(0x80010016);
    uint32_t base =
        whence == 1 ? file->off : whence == 2 ? file->size : 0;
    if (offset < -(int64_t)base) return -1;
    if (offset > (int64_t)UINT32_MAX - base)
        return (int64_t)(int32_t)UINT32_C(0x80010016);
    file->off = (uint32_t)((int64_t)base + offset);
    return file->off;
}

static uint32_t mgspo_byte_ioctl(
    uint32_t fd, uint32_t command,
    uint32_t input, uint32_t input_size,
    uint32_t output, uint32_t output_size,
    uint32_t *delay) {
    if (command != UINT32_C(0x01030008))
        return io_ioctl(
            fd, command, input, input_size, output, output_size, delay);
    if (delay) *delay += 100u;
    if (input_size < 4 || !io_guest_span(input, 4))
        return UINT32_C(0x80010016);
    uint32_t size = MEM_R32(input);
    if (size > output_size || !io_guest_span(output, size))
        return UINT32_C(0x80010016);
    if (delay) *delay = 0;
    return mgspo_byte_read(fd, output, size);
}

static int mgspo_block_seek(
    Fd *file, int64_t offset, uint32_t whence,
    int clamp, int64_t *position) {
    int64_t base =
        whence == 1
        ? (int64_t)(file->off / MGSPO_UMD_SECTOR_SIZE)
        : (whence == 2
            ? (int64_t)(file->size / MGSPO_UMD_SECTOR_SIZE)
            : 0);
    int64_t next;
    if (offset > 0 && base > INT64_MAX - offset) {
        next = INT64_MAX;
    } else if (offset < 0 && base < INT64_MIN - offset) {
        next = INT64_MIN;
    } else {
        next = base + offset;
    }
    int64_t limit =
        (int64_t)(file->size / MGSPO_UMD_SECTOR_SIZE);
    if (clamp) {
        if (next < 0) next = 0;
        if (next > limit) next = limit;
    } else if (next < 0 || next > limit) {
        return 0;
    }
    file->off =
        (uint32_t)next * MGSPO_UMD_SECTOR_SIZE;
    *position = next;
    return 1;
}

static uint32_t mgspo_block_ioctl(
    uint32_t fd, uint32_t command,
    uint32_t input, uint32_t input_size,
    uint32_t output, uint32_t output_size,
    uint32_t *delay) {
    const uint32_t invalid_argument = UINT32_C(0x80010016);
    if (!mgspo_fd_is_block_sector(fd))
        return SCE_KERNEL_ERROR_BADF;
    Fd *file = &s_fds[fd];
    if (delay) *delay += 100;

    switch (command) {
        case UINT32_C(0x01020003):
            if (output_size < 4 || !io_guest_span(output, 4))
                return invalid_argument;
            MEM_W32(output, MGSPO_UMD_SECTOR_SIZE);
            return 0;
        case UINT32_C(0x01020004):
        case UINT32_C(0x01d20001):
            if (output_size < 4 || !io_guest_span(output, 4))
                return invalid_argument;
            MEM_W32(
                output, file->off / MGSPO_UMD_SECTOR_SIZE);
            return 0;
        case UINT32_C(0x01010005):
        case UINT32_C(0x01f100a6): {
            if (input_size < 4 || !io_guest_span(input, 16))
                return invalid_argument;
            int64_t offset = (int64_t)(
                ((uint64_t)MEM_R32(input + 4) << 32) |
                MEM_R32(input));
            uint32_t whence = MEM_R32(input + 12);
            if (whence > 2) return invalid_argument;
            int64_t position;
            if (!mgspo_block_seek(
                    file, offset, whence, 0, &position)) {
                return command == UINT32_C(0x01f100a6)
                    ? UINT32_C(0x8001b003)
                    : UINT32_C(0x80010005);
            }
            if (command == UINT32_C(0x01f100a6) && delay)
                *delay += 15000;
            return 0;
        }
        case UINT32_C(0x01020006):
            if (output_size < 4 || !io_guest_span(output, 4))
                return invalid_argument;
            MEM_W32(output, 0);
            return 0;
        case UINT32_C(0x01020007):
            if (output_size < 8 || !io_guest_span(output, 8))
                return invalid_argument;
            MEM_W32(output, file->size);
            MEM_W32(output + 4, 0);
            return 0;
        case UINT32_C(0x01030008): {
            if (input_size < 4 || !io_guest_span(input, 4))
                return invalid_argument;
            uint32_t sectors = MEM_R32(input);
            if (sectors > output_size)
                return invalid_argument;
            if (delay) *delay = 0;
            return mgspo_block_read(fd, output, sectors);
        }
        case UINT32_C(0x01f30003): {
            if (input_size < 4 || !io_guest_span(input, 4))
                return invalid_argument;
            uint32_t sectors = MEM_R32(input);
            if (!sectors || sectors > output_size)
                return invalid_argument;
            if (delay) *delay = 0;
            return mgspo_block_read(fd, output, sectors);
        }
        case UINT32_C(0x01020001):
        case UINT32_C(0x01020002):
        default:
            fprintf(
                stderr,
                "HLE: unsupported UMD sceIoIoctl("
                "%u, %08x, %08x, %u, %08x, %u)\n",
                fd, command, input, input_size,
                output, output_size);
            return UINT32_C(0x80020325);
    }
}

static void mgspo_io_async_execute(
    uint32_t fd, uint32_t *delay) {
    Fd *file = &s_fds[fd];
    *delay = file->async_delay;
    if (!mgspo_fd_is_block_sector(fd)) {
        switch (file->async_op) {
            case IO_ASYNC_READ: {
                uint32_t result =
                    (s_mgspo_io_access[fd] & MGSPO_IO_ACCESS_READ) != 0
                    ? mgspo_byte_read(
                        fd, file->async_addr, file->async_size)
                    : SCE_KERNEL_ERROR_BADF;
                file->async_res = (int64_t)(int32_t)result;
                *delay = file->async_size / 100u;
                if (*delay < 100u) *delay = 100u;
                if (getenv("SR_IOLOG"))
                    fprintf(
                        stderr, "ReadAsync fd=%u dst=0x%x size=%u -> %d\n",
                        fd, file->async_addr, file->async_size,
                        (int32_t)result);
                break;
            }
            case IO_ASYNC_SEEK:
                file->async_res = mgspo_byte_seek(
                    file, file->async_offset, file->async_whence);
                *delay = 100;
                break;
            case IO_ASYNC_IOCTL:
                file->async_res = (int64_t)(int32_t)mgspo_byte_ioctl(
                    fd, file->async_cmd,
                    file->async_addr, file->async_size,
                    file->async_out_addr, file->async_out_size,
                    delay);
                break;
            default:
                io_async_execute(fd, delay);
                return;
        }
        file->async_op = IO_ASYNC_NONE;
        return;
    }
    switch (file->async_op) {
        case IO_ASYNC_OPEN:
            break;
        case IO_ASYNC_READ:
            file->async_res = (int64_t)(int32_t)mgspo_block_read(
                fd, file->async_addr, file->async_size);
            uint64_t read_delay =
                (uint64_t)file->async_size *
                MGSPO_UMD_SECTOR_SIZE / 100;
            *delay = read_delay > UINT32_MAX
                ? UINT32_MAX
                : (uint32_t)read_delay;
            if (*delay < 100) *delay = 100;
            break;
        case IO_ASYNC_SEEK: {
            int64_t position;
            if (mgspo_block_seek(
                    file, file->async_offset,
                    file->async_whence, 1, &position)) {
                file->async_res = position;
            } else {
                file->async_res =
                    (int64_t)(int32_t)UINT32_C(0x80010005);
            }
            *delay = 100;
            break;
        }
        case IO_ASYNC_IOCTL:
            file->async_res = (int64_t)(int32_t)mgspo_block_ioctl(
                fd, file->async_cmd,
                file->async_addr, file->async_size,
                file->async_out_addr, file->async_out_size,
                delay);
            break;
        case IO_ASYNC_CLOSE:
            file->async_res = 0;
            s_mgspo_io_access[fd] = 0;
            *delay = 0;
            break;
        default:
            file->async_res = -1;
            *delay = 0;
            break;
    }
    file->async_op = IO_ASYNC_NONE;
}

static void mgspo_io_async_worker(uint32_t fd) {
    for (;;) {
        if (fd >= 64 || !s_fds[fd].used) {
            sched_exit_delete_current(0);
            return;
        }
        uint32_t delay;
        mgspo_io_async_execute(fd, &delay);
        sched_delay_current(delay);
        if (!s_fds[fd].used) {
            sched_exit_delete_current(0);
            return;
        }
        s_fds[fd].async_pending = 0;
        s_fds[fd].async_ready = 1;
        sched_wake(IO_ASYNC_RESULT_OBJ(fd));
        sched_block_on(IO_ASYNC_START_OBJ(fd));
    }
}

static uint32_t mgspo_io_async_start(uint32_t fd) {
    Fd *file = &s_fds[fd];
    file->async_pending = 1;
    file->async_ready = 0;
    if (!sr_sched_on) {
        uint32_t delay;
        mgspo_io_async_execute(fd, &delay);
        file->async_pending = 0;
        file->async_ready = 1;
        return 0;
    }

    int priority = file->async_priority == -1
        ? sched_current_priority()
        : file->async_priority;
    if (!file->async_thread) {
        uint32_t uid = sched_create_hle_thread(
            "SceIoAsync", priority, 0x200,
            mgspo_io_async_worker, fd);
        if ((int32_t)uid < 0) {
            file->async_pending = 0;
            file->async_op = IO_ASYNC_NONE;
            return uid;
        }
        file->async_thread = uid;
    } else {
        sched_set_priority(file->async_thread, priority);
        sched_wake(IO_ASYNC_START_OBJ(fd));
    }
    sched_preempt();
    return 0;
}

static uint32_t h_mgspo_io_open(CpuState *state) {
    static const uint32_t disc_idle_iterations[] = {5, 4, 4, 7};
    static uint32_t disc_open_count;
    char path[256];
    guest_cstr(state->r[4], path, sizeof(path));
    uint32_t result = mgspo_io_open_core(state, path);
    int disc =
        _strnicmp(path, "disc0:", 6) == 0 ||
        mgspo_is_umd_path(path);
    uint32_t delay = disc ? 4000 : 10000;
    uint32_t iterations = 10;
    if (disc) {
        iterations =
            disc_open_count <
                sizeof(disc_idle_iterations) /
                    sizeof(disc_idle_iterations[0])
            ? disc_idle_iterations[disc_open_count]
            : 4;
        disc_open_count++;
    }
    mgspo_trace_idle_delay(state, iterations, result);
    sched_delay_current(delay);
    state->r[3] = 0;
    return result;
}

static uint32_t h_mgspo_io_open_async(CpuState *state) {
    char path[256];
    guest_cstr(state->r[4], path, sizeof(path));
    uint32_t result = mgspo_io_open_core(state, path);
    uint32_t fd = result;
    if ((int32_t)result < 0) {
        int slot = io_find_slot();
        if (slot < 0) return result;
        fd = (uint32_t)slot;
        memset(&s_fds[fd], 0, sizeof(s_fds[fd]));
        s_fds[fd].used = 1;
        s_fds[fd].close_pending = 1;
        s_fds[fd].async_priority = s_async_default_priority;
        s_fds[fd].async_res = (int64_t)(int32_t)result;
    } else {
        s_fds[fd].async_res = (int64_t)(int32_t)fd;
    }
    Fd *file = &s_fds[fd];
    file->async_op = IO_ASYNC_OPEN;
    file->async_delay = mgspo_is_umd_path(path)
        ? ((int32_t)result < 0 ? 6000u : 4000u)
        : (strstr(path, "sce_lbn") ? 80u :
            (is_disc_path(path)
                ? ((int32_t)result < 0 ? 6000u : 4000u)
                : 10000u));
    uint32_t start = mgspo_io_async_start(fd);
    if ((int32_t)start < 0) {
        io_release_fd(fd);
        return start;
    }
    return fd;
}

static uint32_t h_mgspo_io_read(CpuState *state) {
    uint32_t fd = state->r[4];
    if (fd >= 64 || !s_fds[fd].used)
        return h_IoRead(state);
    if ((s_mgspo_io_access[fd] & MGSPO_IO_ACCESS_READ) == 0)
        return SCE_KERNEL_ERROR_BADF;
    if (io_async_busy(&s_fds[fd]))
        return SCE_KERNEL_ERROR_ASYNC_BUSY;
    return mgspo_fd_is_block_sector(fd)
        ? mgspo_block_read(fd, state->r[5], state->r[6])
        : mgspo_byte_read(fd, state->r[5], state->r[6]);
}

static uint32_t h_mgspo_io_read_async(CpuState *state) {
    uint32_t fd = state->r[4];
    if (fd >= 64 || !s_fds[fd].used)
        return SCE_KERNEL_ERROR_BADF;
    if ((s_mgspo_io_access[fd] & MGSPO_IO_ACCESS_READ) == 0)
        return SCE_KERNEL_ERROR_BADF;
    Fd *file = &s_fds[fd];
    if (io_async_busy(file))
        return SCE_KERNEL_ERROR_ASYNC_BUSY;
    file->async_op = IO_ASYNC_READ;
    file->async_addr = state->r[5];
    file->async_size = state->r[6];
    return mgspo_io_async_start(fd);
}

static uint32_t h_mgspo_io_lseek32(CpuState *state) {
    uint32_t fd = state->r[4];
    if (fd >= 64 || !s_fds[fd].used)
        return h_IoLseek32(state);
    Fd *file = &s_fds[fd];
    if (io_async_busy(file))
        return SCE_KERNEL_ERROR_ASYNC_BUSY;
    if (!mgspo_fd_is_block_sector(fd))
        return (uint32_t)mgspo_byte_seek(
            file, (int32_t)state->r[5], state->r[6]);
    int64_t position;
    mgspo_block_seek(
        file, (int32_t)state->r[5],
        state->r[6], 1, &position);
    return (uint32_t)position;
}

static uint32_t h_mgspo_io_lseek(CpuState *state) {
    uint32_t fd = state->r[4];
    if (fd >= 64 || !s_fds[fd].used)
        return h_IoLseek(state);
    Fd *file = &s_fds[fd];
    if (io_async_busy(file)) {
        state->r[3] = UINT32_MAX;
        return SCE_KERNEL_ERROR_ASYNC_BUSY;
    }
    int64_t offset = (int64_t)(
        ((uint64_t)state->r[7] << 32) |
        state->r[6]);
    int64_t position;
    if (mgspo_fd_is_block_sector(fd)) {
        mgspo_block_seek(file, offset, stack_arg(state, 0), 1, &position);
    } else {
        position = mgspo_byte_seek(file, offset, stack_arg(state, 0));
    }
    state->r[3] = (uint32_t)((uint64_t)position >> 32);
    return (uint32_t)position;
}

static uint32_t h_mgspo_io_lseek_async(CpuState *state) {
    uint32_t fd = state->r[4];
    if (fd >= 64 || !s_fds[fd].used)
        return SCE_KERNEL_ERROR_BADF;
    uint32_t whence = stack_arg(state, 0);
    if (whence > 2) return UINT32_C(0x80010016);
    Fd *file = &s_fds[fd];
    if (io_async_busy(file))
        return SCE_KERNEL_ERROR_ASYNC_BUSY;
    file->async_op = IO_ASYNC_SEEK;
    file->async_offset = (int64_t)(
        ((uint64_t)state->r[7] << 32) |
        state->r[6]);
    file->async_whence = whence;
    return mgspo_io_async_start(fd);
}

static uint32_t h_mgspo_io_ioctl(CpuState *state) {
    uint32_t fd = state->r[4];
    if (fd >= 64 || !s_fds[fd].used)
        return h_IoIoctl(state);
    Fd *file = &s_fds[fd];
    if (io_async_busy(file))
        return SCE_KERNEL_ERROR_ASYNC_BUSY;
    uint32_t delay = 0;
    uint32_t result = mgspo_fd_is_block_sector(fd)
        ? mgspo_block_ioctl(
            fd, state->r[5], state->r[6], state->r[7],
            stack_arg(state, 0), stack_arg(state, 1), &delay)
        : mgspo_byte_ioctl(
            fd, state->r[5], state->r[6], state->r[7],
            stack_arg(state, 0), stack_arg(state, 1), &delay);
    if (delay) sched_delay_current(delay);
    return result;
}

static uint32_t h_mgspo_io_ioctl_async(CpuState *state) {
    uint32_t fd = state->r[4];
    if (fd >= 64 || !s_fds[fd].used)
        return SCE_KERNEL_ERROR_BADF;
    Fd *file = &s_fds[fd];
    if (io_async_busy(file))
        return SCE_KERNEL_ERROR_ASYNC_BUSY;
    file->async_op = IO_ASYNC_IOCTL;
    file->async_cmd = state->r[5];
    file->async_addr = state->r[6];
    file->async_size = state->r[7];
    file->async_out_addr = stack_arg(state, 0);
    file->async_out_size = stack_arg(state, 1);
    file->async_delay = 0;
    return mgspo_io_async_start(fd);
}

static uint32_t h_mgspo_io_close(CpuState *state) {
    static int idle_result_initialized;
    uint32_t fd = state->r[4];
    uint32_t result = h_IoClose(state);
    if (result == 0 && fd < 64)
        s_mgspo_io_access[fd] = 0;
    mgspo_init_idle_state();
    if (!idle_result_initialized) {
        s_mgspo_idle_state.r[2] = 0;
        idle_result_initialized = 1;
    }
    mgspo_trace_idle_delay(state, 1, result);
    sched_delay_current(100);
    state->r[3] = 0;
    return result;
}

static uint32_t h_mgspo_io_close_async(CpuState *state) {
    uint32_t fd = state->r[4];
    if (fd >= 64 || !s_fds[fd].used)
        return SCE_KERNEL_ERROR_BADF;
    Fd *file = &s_fds[fd];
    if (io_async_busy(file))
        return SCE_KERNEL_ERROR_ASYNC_BUSY;
    file->close_pending = 1;
    file->async_op = IO_ASYNC_CLOSE;
    return mgspo_io_async_start(fd);
}

static uint32_t h_mgspo_io_dread(CpuState *state) {
    static const uint32_t first_entry_idle_iterations[] = {2, 1, 2, 3};
    static uint32_t delayed_directory_count;
    DirHandle *directory = dir_find(state->r[4]);
    int first_entry = directory && directory->index == 0;
    DirEntry *entry =
        directory && directory->index < directory->count
        ? &directory->entries[directory->index]
        : NULL;
    uint32_t output = state->r[5];
    uint32_t result = h_IoDread(state);
    if (entry && result == 1) {
        time_t times[3] = {
            entry->ctime_value,
            entry->atime_value,
            entry->mtime_value,
        };
        for (uint32_t index = 0; index < 3; ++index) {
            if (times[index]) continue;
            uint32_t date = output + 0x10 + index * 0x10;
            MEM_W16(date, 1900);
            MEM_W16(date + 2, 1);
            MEM_W16(date + 4, 0);
        }
        for (uint32_t index = 0; index < 0x14; ++index)
            MEM_W8(output + 0x44 + index, 0xfe);
    }
    if (first_entry && result == 1) {
        uint32_t iterations =
            delayed_directory_count <
                sizeof(first_entry_idle_iterations) /
                    sizeof(first_entry_idle_iterations[0])
            ? first_entry_idle_iterations[delayed_directory_count]
            : 1;
        delayed_directory_count++;
        mgspo_trace_idle_delay(state, iterations, result);
        sched_delay_current(1000);
        state->r[3] = 0;
    }
    return result;
}

static int mgspo_verify_byte_mode_path(
    const char *path, uint32_t path_address,
    uint32_t output_address) {
    size_t path_size = strlen(path) + 1;
    memcpy(SR_HOST(path_address), path, path_size);
    CpuState state;
    memset(&state, 0, sizeof(state));
    state.r[4] = path_address;
    state.r[5] = 1;
    uint32_t fd = mgspo_io_open_core(&state, path);
    if ((int32_t)fd < 0) {
        fprintf(
            stderr,
            "ERROR: UMD contract could not open byte-mode path "
            "\"%s\" (0x%08x).\n",
            path, fd);
        return 0;
    }
    Fd *file = &s_fds[fd];
    uint32_t result = io_read(fd, output_address, 1);
    int valid =
        result == 1 && file->off == 1 && file->size < UINT32_MAX - 3;
    uint32_t beyond = file->size + 1;
    memset(SR_HOST(output_address), 0xcc, 64);

    state.r[4] = fd;
    state.r[5] = beyond;
    state.r[6] = 0;
    valid = valid && h_mgspo_io_lseek32(&state) == beyond;
    state.r[6] = beyond;
    state.r[7] = 0;
    state.r[8] = 0;
    valid =
        valid && h_mgspo_io_lseek(&state) == beyond &&
        state.r[3] == 0;
    state.r[6] = 0;
    state.r[7] = 1;
    valid =
        valid &&
        h_mgspo_io_lseek(&state) == UINT32_C(0x80010016) &&
        state.r[3] == UINT32_MAX &&
        file->off == beyond;
    state.r[5] = output_address;
    state.r[6] = 8;
    valid =
        valid && h_mgspo_io_read(&state) == 0 &&
        file->off == beyond &&
        MEM_R8(output_address) == 0xcc;

    state.r[6] = 2;
    state.r[7] = 0;
    state.r[8] = 1;
    valid = valid && h_mgspo_io_lseek_async(&state) == 0;
    state.r[5] = output_address + 16;
    valid =
        valid && h_IoWaitAsync(&state) == 0 &&
        MEM_R32(output_address + 16) == beyond + 2 &&
        MEM_R32(output_address + 20) == 0 &&
        file->off == beyond + 2;

    state.r[5] = output_address;
    state.r[6] = 8;
    valid = valid && h_mgspo_io_read_async(&state) == 0;
    state.r[5] = output_address + 16;
    valid =
        valid && h_IoWaitAsync(&state) == 0 &&
        MEM_R32(output_address + 16) == 0 &&
        MEM_R32(output_address + 20) == 0 &&
        file->off == beyond + 2 &&
        MEM_R8(output_address) == 0xcc;

    MEM_W32(output_address + 32, 4);
    uint32_t delay = 0;
    valid =
        valid &&
        mgspo_byte_ioctl(
            fd, UINT32_C(0x01030008), output_address + 32, 4,
            output_address, 4, &delay) == 0 &&
        file->off == beyond + 2 &&
        MEM_R8(output_address) == 0xcc;
    delay = 0;
    valid =
        valid &&
        mgspo_byte_ioctl(
            fd, UINT32_C(0x01030008), output_address + 32, 0,
            output_address, 4, &delay) == UINT32_C(0x80010016) &&
        delay == 100;

    state.r[5] = UINT32_MAX;
    state.r[6] = 0;
    valid =
        valid && h_mgspo_io_lseek32(&state) == UINT32_MAX &&
        file->off == beyond + 2;
    state.r[5] = file->size - 1;
    valid = valid && h_mgspo_io_lseek32(&state) == file->size - 1;
    state.r[5] = output_address;
    state.r[6] = UINT32_MAX;
    valid =
        valid && h_mgspo_io_read(&state) == 1 &&
        file->off == file->size &&
        MEM_R8(output_address + 1) == 0xcc;

    io_release_fd(fd);
    if (!valid) {
        fprintf(
            stderr,
            "ERROR: byte-mode seek/read contract mismatch for "
            "\"%s\".\n",
            path);
    }
    return valid;
}

static int mgspo_verify_no_read_access(
    const char *path, uint32_t path_address,
    uint32_t output_address) {
    memcpy(SR_HOST(path_address), path, strlen(path) + 1);
    CpuState state;
    memset(&state, 0, sizeof(state));
    state.r[4] = path_address;
    uint32_t fd = mgspo_io_open_core(&state, path);
    if ((int32_t)fd < 0) return 0;

    memset(SR_HOST(output_address), 0xcc, 1);
    state.r[4] = fd;
    state.r[5] = output_address;
    state.r[6] = 1;
    int valid =
        h_mgspo_io_read(&state) == SCE_KERNEL_ERROR_BADF &&
        s_fds[fd].off == 0 &&
        MEM_R8(output_address) == 0xcc;
    io_release_fd(fd);
    s_mgspo_io_access[fd] = 0;
    if (!valid) {
        fprintf(
            stderr,
            "ERROR: byte-mode read access contract mismatch for "
            "\"%s\".\n",
            path);
    }
    return valid;
}

static int mgspo_verify_disc_normalization(void) {
    static const char *const paths[] = {
        "disc0:/./UMD_DATA.BIN",
        "disc0://UMD_DATA.BIN",
        "disc0:/././UMD_DATA.BIN",
    };
    uint32_t expected_lba = 0;
    uint32_t expected_size = 0;
    if (iso_lookup("disc0:/UMD_DATA.BIN", &expected_lba, &expected_size) != 0)
        return 0;
    for (size_t index = 0; index < sizeof(paths) / sizeof(paths[0]); ++index) {
        uint32_t lba = 0;
        uint32_t size = 0;
        if (iso_lookup(paths[index], &lba, &size) != 0 ||
            lba != expected_lba || size != expected_size) {
            fprintf(stderr, "ERROR: disc path normalization mismatch: %s\n", paths[index]);
            return 0;
        }
    }

    IsoDirEntry expected;
    IsoDirEntry actual;
    int expected_count = 0;
    int actual_count = 0;
    if (iso_list("disc0:/PSP_GAME/USRDIR", &expected, 1, &expected_count) != 0 ||
        iso_list("disc0:/PSP_GAME/./USRDIR", &actual, 1, &actual_count) != 0 ||
        expected_count < 1 || actual_count != expected_count ||
        strcmp(expected.name, actual.name) != 0 ||
        expected.lba != actual.lba || expected.size != actual.size ||
        expected.is_dir != actual.is_dir ||
        iso_lookup("disc0:/../UMD_DATA.BIN", &expected_lba, &expected_size) == 0) {
        fprintf(stderr, "ERROR: disc directory normalization contract mismatch.\n");
        return 0;
    }
    return 1;
}

int mgspo_hle_verify_umd_contract(void) {
    static const char *aliases[] = {"umd0:", "umd1:", "umd:"};
    const uint32_t output_address = UINT32_C(0x09ff0000);
    const uint32_t path_address = UINT32_C(0x09ff1000);
    uint8_t expected[MGSPO_UMD_SECTOR_SIZE];
    uint32_t sectors =
        (uint32_t)(SR_EXPECTED_ISO_SIZE / MGSPO_UMD_SECTOR_SIZE);

    for (size_t index = 0;
         index < sizeof(aliases) / sizeof(aliases[0]);
         ++index) {
        CpuState state;
        memset(&state, 0, sizeof(state));
        state.r[5] = 1;
        uint32_t fd = mgspo_io_open_umd(&state, aliases[index]);
        if ((int32_t)fd < 0 || !mgspo_fd_is_block_sector(fd) ||
            s_fds[fd].size != (uint32_t)SR_EXPECTED_ISO_SIZE) {
            fprintf(
                stderr,
                "ERROR: UMD contract could not open whole device "
                "\"%s\".\n",
                aliases[index]);
            if ((int32_t)fd >= 0) io_release_fd(fd);
            return 0;
        }

        if (index == 0) {
            int64_t position;
            mgspo_block_seek(&s_fds[fd], 16, 0, 1, &position);
            uint32_t result =
                mgspo_block_read(fd, output_address, 1);
            if (iso_read(0, 16 * MGSPO_UMD_SECTOR_SIZE,
                    expected, sizeof(expected)) != sizeof(expected) ||
                result != 1 ||
                memcmp(
                    SR_HOST(output_address),
                    expected, sizeof(expected)) != 0) {
                fprintf(
                    stderr,
                    "ERROR: UMD contract sector read mismatch.\n");
                io_release_fd(fd);
                return 0;
            }

            mgspo_block_seek(&s_fds[fd], 17, 0, 1, &position);
            s_fds[fd].async_op = IO_ASYNC_READ;
            s_fds[fd].async_addr = output_address;
            s_fds[fd].async_size = 1;
            uint32_t async_delay = 0;
            mgspo_io_async_execute(fd, &async_delay);
            if (iso_read(0, 17 * MGSPO_UMD_SECTOR_SIZE,
                    expected, sizeof(expected)) != sizeof(expected) ||
                s_fds[fd].async_res != 1 ||
                async_delay != 100 ||
                memcmp(
                    SR_HOST(output_address),
                    expected, sizeof(expected)) != 0) {
                fprintf(
                    stderr,
                    "ERROR: UMD contract async sector read mismatch.\n");
                io_release_fd(fd);
                return 0;
            }

            mgspo_block_seek(
                &s_fds[fd], (int64_t)sectors - 1,
                0, 1, &position);
            if (mgspo_block_read(fd, output_address, 1) != 1 ||
                mgspo_block_read(fd, output_address, 1) != 0 ||
                s_fds[fd].off != s_fds[fd].size) {
                fprintf(
                    stderr,
                    "ERROR: UMD contract EOF behavior mismatch.\n");
                io_release_fd(fd);
                return 0;
            }

            uint32_t ioctl_output = output_address + 0x800;
            uint32_t delay = 0;
            if (mgspo_block_ioctl(
                    fd, UINT32_C(0x01020003),
                    0, 0, ioctl_output, 4, &delay) != 0 ||
                MEM_R32(ioctl_output) != MGSPO_UMD_SECTOR_SIZE ||
                mgspo_block_ioctl(
                    fd, UINT32_C(0x01020007),
                    0, 0, ioctl_output, 8, &delay) != 0 ||
                MEM_R32(ioctl_output) !=
                    (uint32_t)SR_EXPECTED_ISO_SIZE ||
                MEM_R32(ioctl_output + 4) != 0) {
                fprintf(
                    stderr,
                    "ERROR: UMD contract ioctl mismatch.\n");
                io_release_fd(fd);
                return 0;
            }
        }
        io_release_fd(fd);
    }

    if (!mgspo_verify_byte_mode_path(
            "disc0:/PSP_GAME/PARAM.SFO",
            path_address, output_address) ||
        !mgspo_verify_byte_mode_path(
            "disc0:/sce_lbn0x10_size0x800",
            path_address, output_address) ||
        !mgspo_verify_no_read_access(
            "disc0:/PSP_GAME/PARAM.SFO",
            path_address, output_address) ||
        !mgspo_verify_disc_normalization()) {
        return 0;
    }
    return 1;
}

int mgspo_hle_verify_atrac_contract(void) {
    const uint32_t output = UINT32_C(0x09ff1800);
    CpuState state;
    memset(&state, 0, sizeof(state));
    state.r[4] = 7;
    state.r[5] = output;
    memset(&s_atrac[7], 0, sizeof(s_atrac[7]));
    s_atrac[7].used = 1;
    s_atrac[7].codec = ATRAC_CODEC_PLUS;
    uint32_t result = h_mgspo_atrac_get_max_sample(&state);
    int valid =
        result == 0 &&
        MEM_R32(output) == ATRAC_SAMPLES_PER_FRAME;
    s_atrac[7].codec = ATRAC_CODEC_AT3;
    valid =
        valid &&
        h_mgspo_atrac_get_max_sample(&state) == 0 &&
        MEM_R32(output) == ATRAC3_SAMPLES_PER_FRAME;
    memset(&s_atrac[7], 0, sizeof(s_atrac[7]));
    state.r[4] = 8;
    valid =
        valid &&
        h_mgspo_atrac_get_max_sample(&state) ==
            UINT32_C(0x80630002);
    if (!valid)
        fprintf(
            stderr,
            "ERROR: ATRAC max-sample contract mismatch.\n");
    return valid;
}

void sr_mgspo_register_core_hle_overrides(void) {
    s_hcount_vc = s_vcount;
    s_hcount_intra = MGSPO_INITIAL_HCOUNT;
    sr_hle_register(
        UINT32_C(0x7591c7db),
        "sceKernelSetCompiledSdkVersion",
        h_mgspo_set_compiled_sdk_version);
    sr_hle_register(
        UINT32_C(0x4e3a1105),
        "sceKernelWaitSema",
        h_mgspo_wait_sema);
    sr_hle_register(
        UINT32_C(0x6d212bac),
        "sceKernelWaitSemaCB",
        h_mgspo_wait_sema_cb);
    sr_hle_register(
        UINT32_C(0x3f53e640),
        "sceKernelSignalSema",
        h_mgspo_signal_sema);
    sr_hle_register(
        UINT32_C(0x58b1f937),
        "sceKernelPollSema",
        h_mgspo_poll_sema);
    sr_hle_register(
        UINT32_C(0x28b6489c),
        "sceKernelDeleteSema",
        h_mgspo_delete_sema);
    sr_hle_register(
        UINT32_C(0xea748e31),
        "sceKernelChangeCurrentThreadAttr",
        h_mgspo_change_current_thread_attr);
    sr_hle_register(
        UINT32_C(0x2c34e053),
        "sceKernelReleaseWaitThread",
        h_mgspo_release_wait_thread);
    sr_hle_register(
        UINT32_C(0x3f7ad767),
        "sceRtcGetCurrentTick",
        h_mgspo_rtc_get_current_tick);
    sr_hle_register(
        UINT32_C(0x011f03c1),
        "sceRtcGetAccumulativeTime",
        h_mgspo_rtc_get_accumulative_time);
    sr_hle_register(
        UINT32_C(0x029ca3b3),
        "sceRtcGetAccumlativeTime",
        h_mgspo_rtc_get_accumulative_time);
    sr_hle_register(
        UINT32_C(0xca1e6945),
        "sceFontGetCharGlyphImage_Clip",
        h_mgspo_font_get_char_glyph_image_clip);
    sr_hle_register(
        UINT32_C(0xc629af26),
        "sceUtilityLoadAvModule",
        h_mgspo_load_av_module);
    sr_hle_register(
        UINT32_C(0x132f1eca),
        "sceAtracReinit",
        h_mgspo_atrac_reinit);
    sr_hle_register(
        UINT32_C(0x7a20e7af),
        "sceAtracSetDataAndGetID",
        h_mgspo_atrac_set_data_and_get_id);
    sr_hle_register(
        UINT32_C(0xd6a5f2f7),
        "sceAtracGetMaxSample",
        h_mgspo_atrac_get_max_sample);
    sr_hle_register(
        UINT32_C(0x109f50bc),
        "sceIoOpen",
        h_mgspo_io_open);
    sr_hle_register(
        UINT32_C(0x89aa9906),
        "sceIoOpenAsync",
        h_mgspo_io_open_async);
    sr_hle_register(
        UINT32_C(0x6a638d83),
        "sceIoRead",
        h_mgspo_io_read);
    sr_hle_register(
        UINT32_C(0xa0b5a7c2),
        "sceIoReadAsync",
        h_mgspo_io_read_async);
    sr_hle_register(
        UINT32_C(0x68963324),
        "sceIoLseek32",
        h_mgspo_io_lseek32);
    sr_hle_register(
        UINT32_C(0x27eb27b8),
        "sceIoLseek",
        h_mgspo_io_lseek);
    sr_hle_register(
        UINT32_C(0x71b19e77),
        "sceIoLseekAsync",
        h_mgspo_io_lseek_async);
    sr_hle_register(
        UINT32_C(0x63632449),
        "sceIoIoctl",
        h_mgspo_io_ioctl);
    sr_hle_register(
        UINT32_C(0xe95a012b),
        "sceIoIoctlAsync",
        h_mgspo_io_ioctl_async);
    sr_hle_register(
        UINT32_C(0x810c4bc3),
        "sceIoClose",
        h_mgspo_io_close);
    sr_hle_register(
        UINT32_C(0xff5940b6),
        "sceIoCloseAsync",
        h_mgspo_io_close_async);
    sr_hle_register(
        UINT32_C(0xe3eb004c),
        "sceIoDread",
        h_mgspo_io_dread);
    sr_hle_register(
        UINT32_C(0x50f0c1ec),
        "sceKernelStartModule",
        h_mgspo_start_module);
    sr_hle_register(
        UINT32_C(0xd1ff982a),
        "sceKernelStopModule",
        h_mgspo_stop_module);
}

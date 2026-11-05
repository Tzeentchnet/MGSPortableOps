#include "../external/psp-recomp/src/rt/recomp.h"

#include <errno.h>
#include <fcntl.h>
#include <io.h>
#include <share.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

const char *mgspo_module_name_for_address(uint32_t address);
int mgspo_module_identity_active(const char *identity);

static const char *const s_case_names[] = {
    "open_archive_canonical",
    "size_archive",
    "read_archive_request_8",
    "close_archive",
    "open_direct",
    "size_direct",
    "seek_direct_start_0",
    "read_direct_prefix_8",
    "seek_direct_start_10",
    "read_direct_middle_4",
    "seek_direct_end_minus_4",
    "read_direct_past_eof_8",
    "read_direct_at_eof_4",
    "seek_direct_beyond_eof_49",
    "read_direct_beyond_eof_4",
    "seek_direct_current_plus_2",
    "close_direct",
    "size_closed_handle",
    "read_invalid_handle",
    "close_invalid_handle",
    "open_device_case",
    "close_device_case",
    "open_backslashes",
    "close_backslashes",
    "open_component_case",
    "close_component_case",
    "open_dot_components",
    "close_dot_components",
    "open_double_slash",
    "close_double_slash",
    "open_missing",
    "open_mode_0",
    "close_mode_0",
    "open_mode_2",
    "close_mode_2",
    "open_archive_for_null_buffer",
    "read_null_buffer",
    "close_after_null_buffer",
    "open_archive_for_repeat_reads",
    "read_archive_zero",
    "read_archive_64",
    "close_after_repeat_reads",
    "open_direct_for_negative_seek",
    "seek_direct_negative_start",
    "close_after_negative_seek",
    "seek_invalid_handle",
    "open_direct_for_invalid_whence",
    "seek_direct_invalid_whence",
    "open_direct_component_case",
    "close_direct_component_case",
    "open_direct_dot_component",
    "close_direct_dot_component",
    "open_direct_double_slash",
    "close_direct_double_slash",
    "open_canonical_file",
    "size_canonical_file",
    "read_canonical_file_full",
    "close_canonical_file",
};

enum {
    MGSPO_KJFS_CASE_COUNT =
        sizeof(s_case_names) / sizeof(s_case_names[0]),
    MGSPO_KJFS_DEFAULT_STOP = 20,
    MGSPO_KJFS_SCRATCH_SIZE = 0x10000,
    MGSPO_KJFS_BUFFER_SIZE = 64,
    MGSPO_KJFS_MAX_BLOCK_RETRIES = 64,
};

typedef struct {
    int stage;
    const char *operation_name;
    uint32_t operation_nid;
    uint32_t operation_pc;
    uint32_t operation_result;
    const char *wait_name;
    uint32_t wait_nid;
    uint32_t wait_pc;
    uint32_t wait_result;
    uint32_t async_result_low;
    uint32_t async_result_high;
    uint32_t delay_pc;
} MgspoKjfsBlockedSpec;

typedef struct {
    const MgspoKjfsBlockedSpec *spec;
    FILE *stream;
    const char *done_path;
    uint32_t retry_limit;
    uint32_t retry_count;
    uint32_t thread_uid;
    int phase;
    int active;
} MgspoKjfsBlockedState;

static const MgspoKjfsBlockedSpec s_blocked_specs[] = {
    {
        20, "sceIoOpen", UINT32_C(0x109f50bc), UINT32_C(0x08b761b8),
        UINT32_C(0x80010002), NULL, 0, 0, 0, 0, 0,
        UINT32_C(0x08b761dc),
    },
    {
        28, "sceIoOpen", UINT32_C(0x109f50bc), UINT32_C(0x08b761b8),
        UINT32_C(0x80010002), NULL, 0, 0, 0, 0, 0,
        UINT32_C(0x08b761dc),
    },
    {
        31, "sceIoRead", UINT32_C(0x6a638d83), UINT32_C(0x08b77cb0),
        UINT32_C(0x80020323), NULL, 0, 0, 0, 0, 0,
        UINT32_C(0x08b77cc4),
    },
    {
        43, "sceIoLseekAsync", UINT32_C(0x71b19e77),
        UINT32_C(0x08b763c4), 0,
        "sceIoWaitAsyncCB", UINT32_C(0x35dbd746),
        UINT32_C(0x08b763d4), 0, UINT32_MAX, UINT32_MAX,
        UINT32_C(0x08b76414),
    },
    {
        45, "sceIoLseekAsync", UINT32_C(0x71b19e77),
        UINT32_C(0x08b763c4), UINT32_C(0x80020323),
        NULL, 0, 0, 0, 0, 0, UINT32_C(0x08b76414),
    },
};

static MgspoKjfsBlockedState s_blocked;

static const MgspoKjfsBlockedSpec *blocked_spec(int stage) {
    for (size_t index = 0;
         index < sizeof(s_blocked_specs) / sizeof(s_blocked_specs[0]);
         ++index) {
        if (s_blocked_specs[index].stage == stage)
            return &s_blocked_specs[index];
    }
    return NULL;
}

static int parse_bound(const char *name, int fallback, int maximum, int *out) {
    const char *text = getenv(name);
    if (!text || !text[0]) {
        *out = fallback;
        return 1;
    }
    errno = 0;
    char *end = NULL;
    long value = strtol(text, &end, 10);
    if (errno || end == text || *end || value < 0 || value > maximum) {
        fprintf(stderr, "KJFS probe: invalid %s: %s\n", name, text);
        return 0;
    }
    *out = (int)value;
    return 1;
}

static int parse_required_bound(const char *name, int maximum, int *out) {
    const char *text = getenv(name);
    if (!text || !text[0]) {
        fprintf(stderr, "KJFS probe: missing %s\n", name);
        return 0;
    }
    errno = 0;
    char *end = NULL;
    long value = strtol(text, &end, 10);
    if (errno || end == text || *end || value < 1 || value > maximum) {
        fprintf(stderr, "KJFS probe: invalid %s: %s\n", name, text);
        return 0;
    }
    *out = (int)value;
    return 1;
}

static int opens_handle(int stage) {
    switch (stage) {
        case 0: case 4: case 20: case 22: case 24: case 26: case 28:
        case 31: case 33: case 35: case 38: case 42: case 46:
        case 48: case 50: case 52: case 54:
            return 1;
        default:
            return 0;
    }
}

static int resolve_export(uint32_t nid, uint32_t expected, uint32_t *target) {
    const char *library = NULL;
    if (!sr_module_find_export("kjfs", nid, target, &library) ||
        !library || strcmp(library, "kjfs") != 0 ||
        *target != expected) {
        fprintf(
            stderr,
            "KJFS probe: expected export 0x%08x at 0x%08x is unavailable\n",
            nid, expected);
        return 0;
    }
    const char *module = mgspo_module_name_for_address(*target);
    if (!module || strcmp(module, "KCEJ_FS") != 0) {
        fprintf(stderr, "KJFS probe: export belongs to an unexpected module\n");
        return 0;
    }
    return 1;
}

static void write_buffer(FILE *stream, uint32_t address) {
    if (!address) return;
    const uint8_t *buffer = SR_HOST(address);
    fputs(",\"buffer_hex\":\"", stream);
    for (int index = 0; index < MGSPO_KJFS_BUFFER_SIZE; ++index)
        fprintf(stream, "%02x", buffer[index]);
    fputs("\",\"guard_before_hex\":\"", stream);
    for (int index = -16; index < 0; ++index)
        fprintf(stream, "%02x", buffer[index]);
    fputs("\",\"guard_after_hex\":\"", stream);
    for (int index = MGSPO_KJFS_BUFFER_SIZE;
         index < MGSPO_KJFS_BUFFER_SIZE + 16; ++index)
        fprintf(stream, "%02x", buffer[index]);
    fputc('"', stream);
}

static int write_path(FILE *stream, uint32_t address) {
    const uint8_t *path = SR_HOST(address);
    const uint8_t *end = memchr(path, 0, 256);
    if (!end) {
        fprintf(stderr, "KJFS probe: path is not terminated\n");
        return 0;
    }
    fputs(",\"path_hex\":\"", stream);
    for (const uint8_t *cursor = path; cursor < end; ++cursor)
        fprintf(stream, "%02x", *cursor);
    fputc('"', stream);
    return !ferror(stream);
}

static int blocked_error(const char *message) {
    fprintf(stderr, "KJFS probe: %s\n", message);
    return -1;
}

static int complete_blocked_probe(void) {
    const MgspoKjfsBlockedSpec *spec = s_blocked.spec;
    int events_ok;
    int marker_ok;
    fprintf(
        s_blocked.stream,
        "{\"event\":\"kjfs_probe_blocked\",\"stage\":%d,\"case\":\"%s\","
        "\"retry_count\":%u,\"operation\":{\"name\":\"%s\",\"nid\":%u,"
        "\"pc\":%u,\"result\":%u}",
        spec->stage, s_case_names[spec->stage], s_blocked.retry_count,
        spec->operation_name, spec->operation_nid, spec->operation_pc,
        spec->operation_result);
    if (spec->wait_name) {
        fprintf(
            s_blocked.stream,
            ",\"wait\":{\"name\":\"%s\",\"nid\":%u,\"pc\":%u,"
            "\"result\":%u,\"async_result_low\":%u,"
            "\"async_result_high\":%u}",
            spec->wait_name, spec->wait_nid, spec->wait_pc,
            spec->wait_result, spec->async_result_low,
            spec->async_result_high);
    }
    fprintf(
        s_blocked.stream,
        ",\"thread_consistent\":true,"
        "\"delay\":{\"name\":\"sceKernelDelayThreadCB\","
        "\"nid\":%u,\"pc\":%u,\"microseconds\":1000000,"
        "\"result\":0}}\n",
        UINT32_C(0x68da9e36), spec->delay_pc);
    events_ok = fflush(s_blocked.stream) == 0;
    if (fclose(s_blocked.stream) != 0)
        events_ok = 0;
    if (!events_ok) {
        return blocked_error("cannot finalize blocked-call events");
    }
    s_blocked.stream = NULL;

    FILE *done = fopen(s_blocked.done_path, "wb");
    if (!done) return blocked_error("cannot create blocked-call marker");
    marker_ok = fprintf(
        done,
        "{\"schema\":1,\"stage\":%d,\"case\":\"%s\","
        "\"retry_count\":%u}\n",
        spec->stage, s_case_names[spec->stage],
        s_blocked.retry_count) >= 0;
    if (fclose(done) != 0)
        marker_ok = 0;
    if (!marker_ok) return blocked_error("cannot write blocked-call marker");
    s_blocked.active = 0;
    return 1;
}

int mgspo_kjfs_probe_observe_syscall(
    const char *name, uint32_t nid, uint32_t pc,
    uint32_t thread_uid, const uint32_t arguments[4],
    uint32_t result) {
    if (!s_blocked.active) return 0;
    const MgspoKjfsBlockedSpec *spec = s_blocked.spec;

    if (nid == spec->operation_nid && pc == spec->operation_pc) {
        if (s_blocked.phase != 0)
            return blocked_error("blocked operation repeated out of order");
        if (strcmp(name, spec->operation_name) != 0 ||
            result != spec->operation_result) {
            return blocked_error("blocked operation result mismatch");
        }
        if (!s_blocked.thread_uid)
            s_blocked.thread_uid = thread_uid;
        if (thread_uid != s_blocked.thread_uid)
            return blocked_error("blocked operation changed threads");
        s_blocked.phase = spec->wait_name ? 1 : 2;
        return 0;
    }

    if (spec->wait_name &&
        nid == spec->wait_nid && pc == spec->wait_pc) {
        if (s_blocked.phase != 1 ||
            thread_uid != s_blocked.thread_uid ||
            strcmp(name, spec->wait_name) != 0 ||
            result != spec->wait_result) {
            return blocked_error("blocked wait result mismatch");
        }
        uint32_t address = arguments[1];
        if (address > UINT32_MAX - 7u ||
            !sr_inrange(address) || !sr_inrange(address + 7) ||
            MEM_R32(address) != spec->async_result_low ||
            MEM_R32(address + 4) != spec->async_result_high) {
            return blocked_error("blocked wait async result mismatch");
        }
        s_blocked.phase = 2;
        return 0;
    }

    if (nid == UINT32_C(0x68da9e36) && pc == spec->delay_pc) {
        if (s_blocked.phase != 2 ||
            thread_uid != s_blocked.thread_uid ||
            strcmp(name, "sceKernelDelayThreadCB") != 0 ||
            arguments[0] != UINT32_C(1000000) ||
            result != 0) {
            return blocked_error("blocked delay result mismatch");
        }
        s_blocked.phase = 0;
        s_blocked.retry_count++;
        if (s_blocked.retry_count == s_blocked.retry_limit)
            return complete_blocked_probe();
    }
    return 0;
}

static int run_case(
    FILE *stream, CpuState *state, uint32_t scratch,
    uint32_t *handle, uint32_t *canonical_file_size, int stage) {
    uint32_t args[5] = {0};
    uint32_t nid = 0;
    uint32_t expected = 0;
    uint32_t buffer = 0;
    int count = 0;
    switch (stage) {
        case 0: case 4: case 20: case 22: case 24: case 26: case 28:
        case 30: case 31: case 33: case 35: case 38: case 42: case 46:
        case 48: case 50: case 52: case 54: {
            static const uint32_t offsets[] = {
                0x0000, 0x0100, 0x0200, 0x0300,
                0x0400, 0x0500, 0x0600,
            };
            int path_index = 0;
            if (stage >= 20 && stage <= 30)
                path_index = 1 + (stage - 20) / 2;
            uint32_t path_offset =
                stage == 54 ? 0 :
                stage >= 48 ? 0x0800 + (uint32_t)(stage - 48) * 0x80 :
                stage == 4 || stage == 42 || stage == 46
                    ? 0x0700 : offsets[path_index];
            args[0] = scratch + path_offset;
            args[1] = stage == 31 ? 0 : stage == 33 ? 2 : 1;
            args[3] = scratch + 0x2000;
            count = 4;
            nid = UINT32_C(0x93e9297f);
            expected = UINT32_C(0x08b762d8);
            break;
        }
        case 1: case 5: case 17: case 55:
            args[0] = *handle;
            count = 1;
            nid = UINT32_C(0x1b969771);
            expected = UINT32_C(0x08b77900);
            break;
        case 2: case 7: case 9: case 11: case 12:
        case 14: case 18: case 36: case 39: case 40: case 56:
            buffer = scratch + 0x1000;
            memset(
                SR_HOST(buffer - 16), 0xcc, MGSPO_KJFS_BUFFER_SIZE + 32);
            args[0] = stage == 18 ? UINT32_C(0x7fffffff) : *handle;
            args[1] = stage == 36 ? 0 : buffer;
            if (stage == 36) buffer = 0;
            switch (stage) {
                case 2: case 7: case 11: args[2] = 8; break;
                case 9: case 12: case 14: case 18: case 36:
                    args[2] = 4; break;
                case 39: args[2] = 0; break;
                case 40: args[2] = 64; break;
                case 56:
                    if (!*canonical_file_size ||
                        *canonical_file_size > MGSPO_KJFS_BUFFER_SIZE) {
                        fprintf(stderr, "KJFS probe: missing canonical file size\n");
                        return 0;
                    }
                    args[2] = *canonical_file_size;
                    break;
            }
            count = 3;
            nid = UINT32_C(0x432f631b);
            expected = UINT32_C(0x08b76778);
            break;
        case 6: case 8: case 10: case 13: case 15:
        case 43: case 45: case 47:
            args[0] = stage == 45 ? UINT32_C(0x7fffffff) : *handle;
            switch (stage) {
                case 6: break;
                case 8: args[2] = 10; break;
                case 10:
                    args[2] = UINT32_C(0xfffffffc);
                    args[3] = UINT32_MAX;
                    args[4] = 2;
                    break;
                case 13: args[2] = 49; break;
                case 15: args[2] = 2; args[4] = 1; break;
                case 43:
                    args[2] = UINT32_MAX;
                    args[3] = UINT32_MAX;
                    break;
                case 45: break;
                case 47: args[4] = 3; break;
            }
            count = 5;
            nid = UINT32_C(0x1ecf095d);
            expected = UINT32_C(0x08b76338);
            break;
        case 3: case 16: case 21: case 23: case 25: case 27: case 29:
        case 32: case 34: case 37: case 41: case 44: case 19:
        case 49: case 51: case 53: case 57:
            args[0] = stage == 19 ? UINT32_C(0x7fffffff) : *handle;
            count = 1;
            nid = UINT32_C(0x2b9b31b4);
            expected = UINT32_C(0x08b76c18);
            break;
        default:
            fprintf(stderr, "KJFS probe: invalid case %d\n", stage);
            return 0;
    }

    uint32_t target = 0;
    if (!resolve_export(nid, expected, &target)) return 0;
    CpuState saved = *state;
    if (saved.r[29] < 128 ||
        !sr_inrange(saved.r[29] - 128) ||
        !sr_inrange(saved.r[29] - 1)) {
        fprintf(stderr, "KJFS probe: guest stack is not writable\n");
        return 0;
    }
    state->r[29] = saved.r[29] - 128;
    state->r[31] = UINT32_C(0x08000018);
    for (int index = 0; index < count; ++index)
        state->r[4 + index] = args[index];

    fprintf(
        stream,
        "{\"event\":\"kjfs_probe_case\",\"phase\":\"call\","
        "\"stage\":%d,\"case\":\"%s\",\"args\":[",
        stage, s_case_names[stage]);
    for (int index = 0; index < count; ++index)
        fprintf(stream, "%s%u", index ? "," : "", args[index]);
    fputc(']', stream);
    if (nid == UINT32_C(0x93e9297f) && !write_path(stream, args[0]))
        return 0;
    fputs("}\n", stream);
    if (fflush(stream) != 0) return 0;

    if (s_blocked.spec && stage == s_blocked.spec->stage) {
        s_blocked.active = 1;
        s_blocked.phase = 0;
        s_blocked.retry_count = 0;
        s_blocked.thread_uid = 0;
    }
    dispatch(state, target);
    if (s_blocked.active) {
        fprintf(stderr, "KJFS probe: expected blocked call returned\n");
        *state = saved;
        return 0;
    }
    uint32_t result = state->r[2];
    if (stage == 55) {
        if (!result || result > MGSPO_KJFS_BUFFER_SIZE) {
            fprintf(stderr, "KJFS probe: canonical file size is invalid\n");
            *state = saved;
            return 0;
        }
        *canonical_file_size = result;
    }
    fprintf(
        stream,
        "{\"event\":\"kjfs_probe_case\",\"phase\":\"return\","
        "\"stage\":%d,\"case\":\"%s\","
        "\"result\":%u,\"result_hi\":%u",
        stage, s_case_names[stage], result, state->r[3]);
    write_buffer(stream, buffer);
    fputs("}\n", stream);
    if (fflush(stream) != 0) return 0;
    if (opens_handle(stage)) *handle = result;
    *state = saved;
    return !ferror(stream);
}

int mgspo_kjfs_probe_run(CpuState *state, const char *path) {
    int start = 0;
    int stop = 0;
    if (!mgspo_module_identity_active("KCEJ_FS") ||
        !parse_bound(
            "MGSPO_KJFS_PROBE_STAGE", 0, MGSPO_KJFS_CASE_COUNT - 1, &start) ||
        !parse_bound(
            "MGSPO_KJFS_PROBE_STOP", MGSPO_KJFS_DEFAULT_STOP,
            MGSPO_KJFS_CASE_COUNT, &stop) ||
        start >= stop) {
        fprintf(stderr, "KJFS probe: invalid range or inactive module\n");
        return 0;
    }

    memset(&s_blocked, 0, sizeof(s_blocked));
    const char *block_stage_text = getenv("MGSPO_KJFS_BLOCK_STAGE");
    if (block_stage_text) {
        int block_stage = 0;
        int retry_limit = 0;
        const char *done_path = getenv("MGSPO_KJFS_BLOCKED_OUTPUT");
        if (!parse_required_bound(
                "MGSPO_KJFS_BLOCK_STAGE",
                MGSPO_KJFS_CASE_COUNT - 1, &block_stage) ||
            !parse_required_bound(
                "MGSPO_KJFS_BLOCK_RETRIES",
                MGSPO_KJFS_MAX_BLOCK_RETRIES, &retry_limit) ||
            !done_path || !done_path[0]) {
            fprintf(stderr, "KJFS probe: invalid blocked-call configuration\n");
            return 0;
        }
        s_blocked.spec = blocked_spec(block_stage);
        int expected_start = block_stage == 43 ? 42 : block_stage;
        if (!s_blocked.spec ||
            start != expected_start ||
            stop != block_stage + 1) {
            fprintf(stderr, "KJFS probe: invalid blocked-call range\n");
            return 0;
        }
        s_blocked.done_path = done_path;
        s_blocked.retry_limit = (uint32_t)retry_limit;
    } else if (
        getenv("MGSPO_KJFS_BLOCK_RETRIES") ||
        getenv("MGSPO_KJFS_BLOCKED_OUTPUT")) {
        fprintf(stderr, "KJFS probe: incomplete blocked-call configuration\n");
        return 0;
    }

    int descriptor = -1;
    errno_t error = _sopen_s(
        &descriptor, path, _O_WRONLY | _O_CREAT | _O_EXCL | _O_BINARY,
        _SH_DENYRW, _S_IREAD | _S_IWRITE);
    if (error) {
        fprintf(stderr, "KJFS probe: cannot create %s: %s\n", path, strerror(error));
        return 0;
    }
    FILE *stream = _fdopen(descriptor, "wb");
    if (!stream) {
        fprintf(stderr, "KJFS probe: cannot open output stream: %s\n", strerror(errno));
        _close(descriptor);
        return 0;
    }
    s_blocked.stream = stream;

    uint32_t size = MGSPO_KJFS_SCRATCH_SIZE;
    uint32_t scratch = sr_ba_alloc(sr_kmem_user(), &size, 1, "KJFS probe");
    if (scratch == SR_BA_FAIL) {
        fprintf(stderr, "KJFS probe: cannot allocate guest scratch memory\n");
        fclose(stream);
        return 0;
    }
    memset(SR_HOST(scratch), 0xcc, MGSPO_KJFS_SCRATCH_SIZE);
    static const char *const paths[] = {
        "disc0:/PSP_GAME/USRDIR/stage/init/data.cnf",
        "DISC0:/PSP_GAME/USRDIR/stage/init/data.cnf",
        "disc0:\\PSP_GAME\\USRDIR\\stage\\init\\data.cnf",
        "disc0:/psp_game/usrdir/STAGE/INIT/DATA.CNF",
        "disc0:/PSP_GAME/USRDIR/stage/./init/../init/data.cnf",
        "disc0:/PSP_GAME//USRDIR///stage/init/data.cnf",
        "disc0:/PSP_GAME/USRDIR/stage/init/__mgspo_missing__.bin",
        "disc0:/UMD_DATA.BIN",
        "disc0:/umd_data.bin",
        "disc0:/./UMD_DATA.BIN",
        "disc0://UMD_DATA.BIN",
    };
    for (size_t index = 0; index < sizeof(paths) / sizeof(paths[0]); ++index)
        memcpy(SR_HOST(scratch + (uint32_t)index * 0x100), paths[index], strlen(paths[index]) + 1);

    fprintf(
        stream,
        "{\"event\":\"kjfs_probe_start\",\"scratch\":%u,"
        "\"start_stage\":%d,\"stop_stage\":%d}\n",
        scratch, start, stop);
    uint32_t handle = 0;
    uint32_t canonical_file_size = 0;
    int ok = 1;
    for (int stage = start; stage < stop; ++stage) {
        if (!run_case(
                stream, state, scratch, &handle, &canonical_file_size, stage)) {
            ok = 0;
            break;
        }
    }
    if (ok) fputs("{\"event\":\"kjfs_probe_done\"}\n", stream);
    if (fflush(stream) != 0) ok = 0;
    if (fclose(stream) != 0) ok = 0;
    if (!sr_ba_free(sr_kmem_user(), scratch)) ok = 0;
    memset(&s_blocked, 0, sizeof(s_blocked));
    if (!ok) fprintf(stderr, "KJFS probe: output or guest execution failed\n");
    return ok;
}

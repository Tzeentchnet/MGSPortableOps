#define _CRT_SECURE_NO_WARNINGS

#include "mgspo_boot_contract.h"
#include "mgspo_log.h"
#include "mgspo_runtime_settings.h"
#include "graphics_config.h"
#include "graphics_settings.h"
#include "input_config.h"
#include "input_settings.h"
#include "recomp.h"
#include "startup_check.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>

void sr_register_all(void);
void sr_mgspo_register_module_policy(void);
void sr_mgspo_register_hle_overrides(void);

static CpuState *s_live_cpu;
static const char *s_trace_path;

int mgspo_hle_verify_umd_contract(void);
int mgspo_hle_verify_atrac_contract(void);
int mgspo_vfpu_verify_contract(void);
int mgspo_module_verify_policy_contract(void);
int mgspo_module_verify_plaintext_contract(void);
#ifdef MGSPO_D3D12_EXPERIMENTAL
int mgspo_d3d12_install_write_coherency(void);
#endif

typedef struct LaunchOptions {
    int configure;
    int configure_input;
    int headless;
    int verbose;
    int verify_contract;
    int trace_steps_set;
    const char *log_path;
    const char *trace_path;
    unsigned long long trace_steps;
} LaunchOptions;

static void print_usage(FILE *stream, const char *program) {
    fprintf(
        stream,
        "Usage: %s [--headless --trace PATH [--trace-steps N]] "
        "[--log PATH] [--verbose]\n"
        "\n"
#ifdef MGSPO_D3D12_EXPERIMENTAL
        "  no arguments       Launch with the configured renderer "
        "(experimental D3D12 build).\n"
#else
        "  no arguments       Launch with the Win32 software renderer.\n"
#endif
        "  --configure        Edit graphics and input settings, then optionally play.\n"
        "  --configure-input  Edit keyboard, mouse, and controller settings.\n"
        "  --headless         Run without a window (trace or service probe).\n"
        "  --trace PATH       Write a deterministic " MGSPO_GAME_TITLE
        " CPU trace.\n"
        "  --trace-steps N    Stop a trace after N instructions "
        "(1-50000000).\n"
        "  --log PATH         Write structured JSON Lines runtime events.\n"
        "  --verify-contract  Verify measured state and title HLE overrides.\n"
        "  --verbose          Enable runtime HLE, scheduler, and module logs.\n"
        "  --help             Show this help.\n",
        program);
}

static int parse_trace_steps(const char *text, unsigned long long *steps) {
    char *end = NULL;
    errno = 0;
    unsigned long long value = _strtoui64(text, &end, 10);
    if (errno || !text[0] || !end || *end || value < 1 || value > 50000000) {
        fprintf(
            stderr,
            "ERROR: --trace-steps must be an integer from 1 to 50000000.\n");
        return 0;
    }
    *steps = value;
    return 1;
}

static int parse_options(int argc, char **argv, LaunchOptions *options) {
    memset(options, 0, sizeof(*options));
    options->trace_steps = MGSPO_TRACE_STEPS;
    for (int index = 1; index < argc; ++index) {
        const char *argument = argv[index];
        if (strcmp(argument, "--help") == 0) {
            print_usage(stdout, argv[0]);
            return 1;
        }
        if (strcmp(argument, "--headless") == 0) {
            options->headless = 1;
            continue;
        }
        if (strcmp(argument, "--configure") == 0) {
            options->configure = 1;
            continue;
        }
        if (strcmp(argument, "--configure-input") == 0) {
            options->configure_input = 1;
            continue;
        }
        if (strcmp(argument, "--verbose") == 0) {
            options->verbose = 1;
            continue;
        }
        if (strcmp(argument, "--verify-contract") == 0) {
            options->verify_contract = 1;
            continue;
        }
        if (strcmp(argument, "--log") == 0) {
            if (++index >= argc || !argv[index][0]) {
                fprintf(stderr, "ERROR: --log requires a path.\n");
                return -1;
            }
            options->log_path = argv[index];
            continue;
        }
        if (strncmp(argument, "--log=", 6) == 0 && argument[6]) {
            options->log_path = argument + 6;
            continue;
        }
        if (strcmp(argument, "--trace") == 0) {
            if (++index >= argc || !argv[index][0]) {
                fprintf(stderr, "ERROR: --trace requires a path.\n");
                return -1;
            }
            options->trace_path = argv[index];
            options->headless = 1;
            continue;
        }
        if (strncmp(argument, "--trace=", 8) == 0 && argument[8]) {
            options->trace_path = argument + 8;
            options->headless = 1;
            continue;
        }
        if (strcmp(argument, "--trace-steps") == 0) {
            if (++index >= argc ||
                !parse_trace_steps(argv[index], &options->trace_steps)) {
                return -1;
            }
            options->trace_steps_set = 1;
            continue;
        }
        if (strncmp(argument, "--trace-steps=", 14) == 0) {
            if (!parse_trace_steps(
                    argument + 14, &options->trace_steps)) {
                return -1;
            }
            options->trace_steps_set = 1;
            continue;
        }
        fprintf(stderr, "ERROR: unknown option: %s\n", argument);
        print_usage(stderr, argv[0]);
        return -1;
    }
    if (options->trace_steps_set && !options->trace_path) {
        fprintf(stderr, "ERROR: --trace-steps requires --trace.\n");
        return -1;
    }
    if (options->configure && options->configure_input) {
        fprintf(
            stderr,
            "ERROR: --configure and --configure-input cannot be combined.\n");
        return -1;
    }
    if ((options->configure || options->configure_input) &&
        (options->headless || options->verify_contract ||
         options->trace_path || options->log_path)) {
        fprintf(
            stderr,
            "ERROR: configuration options cannot be combined with "
            "runtime, trace, contract, or log options.\n");
        return -1;
    }
    return 0;
}

static int executable_sibling_path(
    const char *name, char *path, size_t path_size) {
    if (!path_size || path_size > MAXDWORD) return 0;
    DWORD length = GetModuleFileNameA(NULL, path, (DWORD)path_size);
    if (!length || length >= path_size) return 0;
    char *slash = strrchr(path, '\\');
    char *forward_slash = strrchr(path, '/');
    if (!slash || (forward_slash && forward_slash > slash))
        slash = forward_slash;
    if (!slash) return 0;
    size_t prefix_length = (size_t)(slash - path) + 1;
    size_t name_length = strlen(name);
    if (prefix_length + name_length >= path_size) return 0;
    memcpy(path + prefix_length, name, name_length + 1);
    return 1;
}

static uint8_t *read_boot_image(const char *path, uint32_t *size) {
    FILE *file = fopen(path, "rb");
    if (!file) {
        fprintf(stderr, "ERROR: cannot open boot image \"%s\".\n", path);
        return NULL;
    }
    if (_fseeki64(file, 0, SEEK_END) != 0) {
        fprintf(stderr, "ERROR: cannot seek boot image \"%s\".\n", path);
        fclose(file);
        return NULL;
    }
    __int64 length = _ftelli64(file);
    if (length != MGSPO_MODULE_IMAGE_SIZE) {
        fprintf(
            stderr,
            "ERROR: boot image size is %lld bytes; expected %u.\n",
            (long long)length,
            MGSPO_MODULE_IMAGE_SIZE);
        fclose(file);
        return NULL;
    }
    if (_fseeki64(file, 0, SEEK_SET) != 0) {
        fprintf(stderr, "ERROR: cannot rewind boot image \"%s\".\n", path);
        fclose(file);
        return NULL;
    }
    uint8_t *image = (uint8_t *)malloc((size_t)length);
    if (!image) {
        fprintf(stderr, "ERROR: out of memory while loading boot image.\n");
        fclose(file);
        return NULL;
    }
    if (fread(image, 1, (size_t)length, file) != (size_t)length) {
        fprintf(stderr, "ERROR: cannot read complete boot image \"%s\".\n", path);
        free(image);
        fclose(file);
        return NULL;
    }
    if (fclose(file) != 0) {
        fprintf(stderr, "ERROR: cannot close boot image \"%s\".\n", path);
        free(image);
        return NULL;
    }
    *size = (uint32_t)length;
    return image;
}

static int configure_runtime_assets(void) {
    char path[MAX_PATH];
    if (!executable_sibling_path(
            "assets\\vfpu", path, sizeof(path)) ||
        _putenv_s("PSP_VFPU_TABLES", path) != 0) {
        fprintf(stderr, "ERROR: cannot configure the VFPU table path.\n");
        return 0;
    }
    if (!executable_sibling_path("font", path, sizeof(path)) ||
        _putenv_s("SR_FONTDIR", path) != 0) {
        fprintf(stderr, "ERROR: cannot configure the PSP font path.\n");
        return 0;
    }
    return 1;
}

#ifdef MGSPO_D3D12_EXPERIMENTAL
static int configure_d3d12_texture_path(void) {
    const char *renderer = getenv("SR_GPU");
    if (renderer && renderer[0] && strcmp(renderer, "d3d12") != 0)
        return 1;

    const char *setting = getenv("SR_GPU_PSP_SAMPLER");
    int title_default = !setting || !setting[0];
    if (title_default) {
        if (_putenv_s("SR_GPU_PSP_SAMPLER", "0") != 0) {
            fprintf(
                stderr,
                "ERROR: cannot configure the D3D12 texture path.\n");
            return 0;
        }
        setting = "0";
    }

    if (strcmp(setting, "0") == 0) {
        fprintf(
            stderr,
            "mgspo: D3D12 hardware texture path enabled (%s)\n",
            title_default ? "title default" : "SR_GPU_PSP_SAMPLER override");
    } else {
        fprintf(
            stderr,
            "mgspo: D3D12 integer-quantized texture path enabled "
            "(SR_GPU_PSP_SAMPLER override)\n");
    }
    return 1;
}
#endif

static void seed_prepared_stack(void) {
    static const uint8_t argument[MGSPO_ARGUMENT_SIZE] =
        MGSPO_BOOT_ARGUMENT_BYTES;
    memset(SR_HOST(MGSPO_STACK_START), 0xff, MGSPO_STACK_SIZE);
    memset(SR_HOST(MGSPO_INITIAL_K0), 0, 0x100);
    MEM_W32(MGSPO_STACK_START, MGSPO_START_UID);
    memcpy(SR_HOST(MGSPO_ARGUMENT_ADDRESS), argument, sizeof(argument));
    MEM_W32(MGSPO_INITIAL_K0 + 0xc0, MGSPO_START_UID);
    MEM_W32(MGSPO_INITIAL_K0 + 0xc8, MGSPO_STACK_START);
    MEM_W32(MGSPO_INITIAL_K0 + 0xf8, UINT32_MAX);
    MEM_W32(MGSPO_INITIAL_K0 + 0xfc, UINT32_MAX);
}

static void seed_cpu(CpuState *cpu) {
    static const uint32_t controls[16] =
        MGSPO_INITIAL_VFPU_CONTROL_VALUES;
    memset(cpu, 0, sizeof(*cpu));
    for (int index = 1; index < 32; ++index)
        cpu->r[index] = MGSPO_INITIAL_GPR_FILL;
    cpu->r[4] = MGSPO_ARGUMENT_SIZE;
    cpu->r[5] = MGSPO_ARGUMENT_ADDRESS;
    cpu->r[26] = MGSPO_INITIAL_K0;
    cpu->r[28] = MGSPO_MODULE_GP;
    cpu->r[29] = MGSPO_INITIAL_SP;
    cpu->r[31] = MGSPO_INITIAL_RA;
    cpu->hi = MGSPO_INITIAL_HI;
    cpu->lo = MGSPO_INITIAL_LO;
    cpu->pc = MGSPO_MODULE_ENTRY;
    for (int index = 0; index < 32; ++index)
        cpu->fi[index] = MGSPO_INITIAL_FPR_FILL;
    for (int index = 0; index < 128; ++index)
        cpu->vi[index] = MGSPO_INITIAL_VFPU_FILL;
    memcpy(cpu->vfpuCtrl, controls, sizeof(controls));
    cpu->fcr31 = MGSPO_INITIAL_FCR31;
    cpu->fpcond = MGSPO_INITIAL_FPCOND;
}

static void print_cpu_state(const CpuState *cpu) {
    if (!cpu) return;
    fprintf(
        stderr,
        "guest: pc=0x%08x hi=0x%08x lo=0x%08x fcr31=0x%08x "
        "fpcond=0x%08x\n",
        cpu->pc, cpu->hi, cpu->lo, cpu->fcr31, cpu->fpcond);
    for (int row = 0; row < 4; ++row) {
        fprintf(stderr, "gpr:");
        for (int column = 0; column < 8; ++column) {
            int index = row * 8 + column;
            fprintf(stderr, " r%d=0x%08x", index, cpu->r[index]);
        }
        fputc('\n', stderr);
    }
}

static void print_threads(void) {
    uint32_t identifiers[64];
    uint32_t count =
        sr_uid_list(SR_TMID_THREAD, identifiers, _countof(identifiers));
    fprintf(
        stderr,
        "threads: current=0x%x known=%u\n",
        sched_current_uid(), count);
    uint32_t shown = count < _countof(identifiers)
        ? count
        : (uint32_t)_countof(identifiers);
    for (uint32_t index = 0; index < shown; ++index) {
        SrThreadStatus status;
        if (sched_thread_status(identifiers[index], &status) == 0) {
            fprintf(
                stderr,
                "  uid=0x%x name=\"%s\" entry=0x%08x status=0x%x "
                "priority=%d stack=0x%08x+0x%x\n",
                identifiers[index], status.name, status.entry, status.status,
                status.currentPriority, status.stack, status.stackSize);
        }
    }
}

static void print_trace_tail(void) {
    if (!s_trace_path) return;
    sr_trace_close();
    FILE *file = fopen(s_trace_path, "rb");
    if (!file) return;
    char buffer[16385];
    if (_fseeki64(file, 0, SEEK_END) != 0) {
        fclose(file);
        return;
    }
    __int64 length = _ftelli64(file);
    __int64 start = length > 16384 ? length - 16384 : 0;
    if (_fseeki64(file, start, SEEK_SET) != 0) {
        fclose(file);
        return;
    }
    size_t read = fread(buffer, 1, sizeof(buffer) - 1, file);
    fclose(file);
    buffer[read] = 0;
    char *tail = buffer + read;
    int lines = 0;
    while (tail > buffer && lines < 16) {
        --tail;
        if (*tail == '\n') ++lines;
    }
    if (tail > buffer) ++tail;
    fprintf(stderr, "recent trace:\n%s", tail);
    if (read && buffer[read - 1] != '\n') fputc('\n', stderr);
}

static LONG WINAPI crash_filter(EXCEPTION_POINTERS *exception) {
    EXCEPTION_RECORD *record = exception->ExceptionRecord;
    mgspo_log_fatal(
        "host_exception",
        "unhandled host exception",
        exception->ExceptionRecord->ExceptionCode,
        s_live_cpu ? s_live_cpu->pc : 0);
    fprintf(
        stderr,
        "FATAL: host_exception code=0x%08lx address=%p last_nid=0x%08x\n",
        record->ExceptionCode, record->ExceptionAddress, sr_last_nid);
    if (record->ExceptionCode == EXCEPTION_ACCESS_VIOLATION &&
        record->NumberParameters >= 2) {
        const uint8_t *address =
            (const uint8_t *)record->ExceptionInformation[1];
        fprintf(
            stderr,
            "memory: operation=%s host=%p",
            record->ExceptionInformation[0] ? "write" : "read",
            address);
        if (g_mem && address >= g_mem - 0x04000000 &&
            address < g_mem + 0x04000000) {
            fprintf(
                stderr,
                " guest=0x%08x",
                (uint32_t)(address - g_mem) + 0x08000000u);
        }
        fputc('\n', stderr);
    }
    fprintf(
        stderr,
        "module: uid=0x%x range=0x%08x-0x%08x entry=0x%08x gp=0x%08x\n",
        MGSPO_MODULE_UID, MGSPO_MODULE_BASE,
        MGSPO_MODULE_BASE + MGSPO_MODULE_IMAGE_SIZE,
        MGSPO_MODULE_ENTRY, MGSPO_MODULE_GP);
    print_cpu_state(s_live_cpu);
    print_threads();
    print_trace_tail();
    fflush(stderr);
    return EXCEPTION_CONTINUE_SEARCH;
}

static void enable_verbose_logs(void) {
    static const char *variables[] = {
        "SR_HLELOG",
        "SR_IOLOG",
        "SR_GELOG",
        "SR_MODLOG",
        "SR_NIDLOG",
        "SR_SYSLOG",
        "SR_THLOG",
    };
    for (size_t index = 0; index < _countof(variables); ++index)
        _putenv_s(variables[index], "1");
}

static int verify_runtime_contract(void) {
    CpuState cpu;
    char image_path[MAX_PATH];
    uint32_t image_size = 0;
    if (!executable_sibling_path(
            MGSPO_BOOT_IMAGE, image_path, sizeof(image_path))) {
        fprintf(stderr, "ERROR: cannot locate the staged boot image.\n");
        return 2;
    }
    uint8_t *image = read_boot_image(image_path, &image_size);
    if (!image) return 2;
    sr_mem_init();
    sr_load_segment(MGSPO_MODULE_BASE, image, image_size);
    free(image);
    seed_prepared_stack();
    seed_cpu(&cpu);

    if (MEM_R32(MGSPO_STACK_START) != MGSPO_START_UID ||
        MEM_R32(MGSPO_INITIAL_K0 + 0xc0) != MGSPO_START_UID ||
        MEM_R32(MGSPO_INITIAL_K0 + 0xc8) != MGSPO_STACK_START ||
        MEM_R32(MGSPO_INITIAL_K0 + 0xf8) != UINT32_MAX ||
        MEM_R32(MGSPO_INITIAL_K0 + 0xfc) != UINT32_MAX ||
        cpu.pc != MGSPO_MODULE_ENTRY ||
        cpu.r[4] != MGSPO_ARGUMENT_SIZE ||
        cpu.r[5] != MGSPO_ARGUMENT_ADDRESS ||
        cpu.r[26] != MGSPO_INITIAL_K0 ||
        cpu.r[28] != MGSPO_MODULE_GP ||
        cpu.r[29] != MGSPO_INITIAL_SP ||
        cpu.r[31] != MGSPO_INITIAL_RA) {
        fprintf(stderr, "ERROR: measured boot-state self-check failed.\n");
        return 2;
    }

    if (_putenv_s("MGSPO_ENABLE_NATIVE_ZLIB", "1") != 0) {
        fprintf(
            stderr,
            "ERROR: cannot enable native ZLIB for module contracts.\n");
        return 2;
    }
    sr_mgspo_register_module_policy();
    sr_register_all();
    if (!sr_lookup(MGSPO_MODULE_ENTRY)) {
        fprintf(stderr, "ERROR: native entry function is not registered.\n");
        return 2;
    }
    sr_hle_init();
    sr_mgspo_register_hle_overrides();
    if (_putenv_s("SR_DISABLE_NATIVE_MODULES", "mgspo_zlib") != 0) {
        fprintf(
            stderr,
            "ERROR: cannot disable native ZLIB for module contracts.\n");
        return 2;
    }
    if (!mgspo_hle_verify_umd_contract() ||
        !mgspo_module_verify_plaintext_contract() ||
        !mgspo_module_verify_policy_contract() ||
        !mgspo_hle_verify_atrac_contract() ||
        !mgspo_vfpu_verify_contract()) {
        return 2;
    }
    memset(&cpu, 0, sizeof(cpu));
    cpu.r[4] = UINT32_C(0x02080010);
    cpu.r[6] = UINT32_C(0x12345678);
    sr_syscall(&cpu, UINT32_C(0x7591c7db));
    if (cpu.r[2] != 0 ||
        cpu.r[4] != UINT32_C(0x02080010) ||
        cpu.r[6] != UINT32_C(0x12345678)) {
        fprintf(
            stderr,
            "ERROR: SDK-version HLE register-preservation self-check "
            "failed.\n");
        return 2;
    }

    memset(&cpu, 0, sizeof(cpu));
    cpu.r[4] = UINT32_C(0x08800000);
    sr_syscall(&cpu, UINT32_C(0xe7c27d1b));
    if (cpu.r[2] != 0 ||
        MEM_R16(UINT32_C(0x08800000)) != MGSPO_RTC_YEAR ||
        MEM_R16(UINT32_C(0x08800002)) != MGSPO_RTC_MONTH ||
        MEM_R16(UINT32_C(0x08800004)) != MGSPO_RTC_DAY ||
        MEM_R16(UINT32_C(0x08800006)) != MGSPO_RTC_HOUR) {
        fprintf(stderr, "ERROR: fixed RTC HLE override self-check failed.\n");
        return 2;
    }

    memset(&cpu, 0, sizeof(cpu));
    cpu.r[4] = 6;
    cpu.r[5] = UINT32_C(0x08800020);
    sr_syscall(&cpu, UINT32_C(0xa5da2406));
    if (cpu.r[2] != 0 || MEM_R32(UINT32_C(0x08800020)) != 60) {
        fprintf(
            stderr,
            "ERROR: system-parameter HLE override self-check failed.\n");
        return 2;
    }

    memset(&cpu, 0, sizeof(cpu));
    cpu.r[4] = UINT32_C(0x08800040);
    sr_syscall(&cpu, UINT32_C(0xc69bebce));
    if (cpu.r[2] != 0 ||
        MEM_R8(UINT32_C(0x08800040)) != 0x12 ||
        MEM_R8(UINT32_C(0x08800045)) != 0xbc) {
        fprintf(stderr, "ERROR: OpenPSID HLE override self-check failed.\n");
        return 2;
    }

    printf(
        "OK: boot image, native entry, measured state, exact encrypted "
        "module policy, plaintext load/unload, native ZLIB policy, title "
        "HLE overrides, UMD block-device semantics, and ATRAC frame sizing "
        "are active; VFPU vasin and vsgn are verified "
        "(stack SHA-256 %s)\n",
        MGSPO_PREPARED_STACK_SHA256);
    return 0;
}

int main(int argc, char **argv) {
    LaunchOptions options;
    int parse_result = parse_options(argc, argv, &options);
    if (parse_result != 0) return parse_result > 0 ? 0 : 2;
    int service_probe = getenv("MGSPO_KJFS_PROBE_OUTPUT") != NULL;

    SetUnhandledExceptionFilter(crash_filter);
    if (options.configure_input) {
        int result;
        if (!sr_input_init()) return 2;
        result = sr_input_settings_show(
            MGSPO_GAME_TITLE " Controls", 0);
        return result < 0 ? 2 : 0;
    }
    if (options.configure) {
        int result;
        if (!sr_graphics_config_init() || !sr_input_init()) return 2;
        result = sr_graphics_settings_show(
            MGSPO_GAME_TITLE " Graphics");
        if (result <= 0) return result < 0 ? 2 : 0;
        result = sr_input_settings_show(
            MGSPO_GAME_TITLE " Controls", 1);
        if (result < 0) return 2;
        if (result != SR_INPUT_SETTINGS_LAUNCH) return 0;
    }

#ifndef MGSPO_TRACE_ENABLED
    if (options.trace_path || (options.headless && !service_probe)) {
        fprintf(
            stderr,
            "ERROR: --trace and normal headless runs require the "
            "mgspo-trace preset.\n");
        return 2;
    }
#else
    if (options.headless && !options.trace_path && !service_probe) {
        fprintf(
            stderr,
            "ERROR: normal headless runs require --trace PATH.\n");
        return 2;
    }
#endif

    if (options.verbose) enable_verbose_logs();
    if (options.log_path && mgspo_log_open(options.log_path) != 0) {
        fprintf(
            stderr,
            "ERROR: cannot open structured log \"%s\".\n",
            options.log_path);
        return 2;
    }
    mgspo_log_runtime("info", "launch", MGSPO_GAME_TITLE);
    if (!configure_runtime_assets()) return 2;
    if (options.verify_contract) {
        int result = verify_runtime_contract();
        mgspo_log_runtime(
            result ? "error" : "info",
            "contract_verification",
            result ? "failed" : "passed");
        mgspo_log_close();
        return result;
    }
    if (!sr_startup_validate()) return 2;

    char image_path[MAX_PATH];
    if (!executable_sibling_path(
            MGSPO_BOOT_IMAGE, image_path, sizeof(image_path))) {
        fprintf(
            stderr,
            "ERROR: cannot locate %s beside the executable.\n",
            MGSPO_BOOT_IMAGE);
        return 2;
    }
    uint32_t image_size = 0;
    uint8_t *image = read_boot_image(image_path, &image_size);
    if (!image) return 2;

    fprintf(
        stderr,
        "startup: game=\"%s\" mode=%s image=\"%s\" contract_stack_sha256=%s\n",
        MGSPO_GAME_TITLE, options.headless ? "headless" : "interactive",
        image_path, MGSPO_PREPARED_STACK_SHA256);
    sr_mem_init();
    sr_load_segment(MGSPO_MODULE_BASE, image, image_size);
    free(image);
    if (sr_loaded_start() != MGSPO_MODULE_BASE ||
        sr_loaded_end() != MGSPO_MODULE_BASE + MGSPO_MODULE_IMAGE_SIZE) {
        fprintf(
            stderr,
            "ERROR: loaded module range is 0x%08x-0x%08x; expected "
            "0x%08x-0x%08x.\n",
            sr_loaded_start(), sr_loaded_end(), MGSPO_MODULE_BASE,
            MGSPO_MODULE_BASE + MGSPO_MODULE_IMAGE_SIZE);
        return 2;
    }

    seed_prepared_stack();
    CpuState cpu;
    seed_cpu(&cpu);
    s_live_cpu = &cpu;

    sr_set_next_uid(MGSPO_NEXT_UID);
    sr_register_uid_type(MGSPO_MODULE_UID, SR_TMID_MODULE);
    sr_ge_set_next_list_id(MGSPO_INITIAL_GE_LIST_ID);
    sr_mgspo_register_module_policy();
    sr_register_all();
    sr_hle_init();
    sr_mgspo_register_hle_overrides();

#ifdef MGSPO_TRACE_ENABLED
    if (options.trace_path) {
        char steps[32];
        snprintf(
            steps, sizeof(steps), "%llu",
            options.trace_steps);
        if (_putenv_s("SR_TRACE_STEPS", steps) != 0) {
            fprintf(stderr, "ERROR: cannot configure trace step bound.\n");
            return 2;
        }
        if (sr_trace_open(
                options.trace_path, "ULUS10202", MGSPO_MODULE_ENTRY) != 0) {
            fprintf(
                stderr,
                "ERROR: cannot open trace output \"%s\".\n",
                options.trace_path);
            return 2;
        }
        s_trace_path = options.trace_path;
        fprintf(
            stderr,
            "trace: path=\"%s\" steps=%llu start=0x%08x\n",
            options.trace_path, options.trace_steps,
            MGSPO_MODULE_ENTRY);
    }
#endif

    if (!options.headless) {
#ifdef MGSPO_D3D12_EXPERIMENTAL
        if (!configure_d3d12_texture_path()) return 2;
#endif
        if (!gui_init(MGSPO_GAME_TITLE)) {
            fprintf(stderr, "ERROR: cannot initialize the renderer.\n");
            return 2;
        }
#ifdef MGSPO_D3D12_EXPERIMENTAL
        if (!mgspo_d3d12_install_write_coherency()) {
            gui_shutdown();
            return 2;
        }
#endif
        mgspo_runtime_settings_enable();
    }
    sched_init(&cpu);
    sched_run(
        MGSPO_MODULE_ENTRY,
        MGSPO_ARGUMENT_SIZE,
        MGSPO_ARGUMENT_ADDRESS,
        0);
    sr_trace_close();
    if (!options.headless) gui_shutdown();
    fprintf(stderr, "shutdown: no runnable guest threads remain.\n");
    mgspo_log_runtime("info", "shutdown", "no runnable guest threads remain");
    mgspo_log_close();
    return 0;
}

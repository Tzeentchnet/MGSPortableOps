#define sr_trace_open sr_mgspo_trace_open_buffered
#define sr_begin sr_mgspo_trace_begin_single
#define sr_end sr_mgspo_trace_end_single
#include "../external/psp-recomp/src/rt/recomp.c"
#undef sr_end
#undef sr_begin
#undef sr_trace_open

void sr_begin(const CpuState *state, uint32_t pc, uint32_t opcode) {
    if (s_trace_step_active)
        sr_mgspo_trace_end_single(state, 0, 0);
    sr_mgspo_trace_begin_single(state, pc, opcode);
}

void sr_end(
    const CpuState *state, uint32_t memory_address, int memory_size) {
    sr_mgspo_trace_end_single(
        state, memory_address, memory_size);
}

int sr_trace_open(const char *path, const char *target, uint32_t start_pc) {
    int result = sr_mgspo_trace_open_buffered(path, target, start_pc);
    if (result != 0 || !s_fp) return result;
    if (setvbuf(s_fp, NULL, _IONBF, 0) != 0) {
        fprintf(stderr, "sr_trace_open: cannot disable trace buffering\n");
        sr_trace_close();
        return -1;
    }
    return 0;
}

int sr_mgspo_trace_active(void) {
    return s_fp != NULL && s_trace_active;
}

void sr_mgspo_trace_append(const char *body) {
    if (!s_fp || !s_trace_active || !body) return;
    fprintf(s_fp, "%llu %s\n", s_step, body);
    s_step++;
    if (s_trace_limit && s_step == s_trace_limit) {
        char done_path[sizeof(s_trace_path) + 6];
        snprintf(done_path, sizeof(done_path), "%s.done", s_trace_path);
        sr_trace_close();
        FILE *done = fopen(done_path, "wb");
        if (!done ||
            fprintf(done, "%llu\n", s_trace_limit) < 0 ||
            fclose(done) != 0) {
            fprintf(
                stderr,
                "trace: cannot write completion marker %s\n",
                done_path);
            abort();
        }
        fprintf(stderr, "trace: completed %llu steps\n", s_trace_limit);
        const char *ram_path = getenv("SR_TRACE_RAM");
        if (ram_path && ram_path[0]) {
            FILE *ram = fopen(ram_path, "wb");
            if (!ram ||
                fwrite(
                    SR_HOST(0x08800000u), 1, 0x01800000u, ram) !=
                    0x01800000u ||
                fclose(ram) != 0) {
                fprintf(
                    stderr,
                    "trace: cannot write RAM snapshot %s\n",
                    ram_path);
                abort();
            }
            fprintf(stderr, "trace: wrote RAM snapshot %s\n", ram_path);
        }
        fflush(stderr);
        _Exit(0);
    }
    if (s_step > 50000000ULL) {
        fprintf(
            stderr,
            "trace: imported interpreter trace exceeded 50M steps\n");
        sr_trace_close();
        abort();
    }
}

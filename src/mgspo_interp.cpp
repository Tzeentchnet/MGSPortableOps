#define sr_interpret_fallback sr_mgspo_interpret_fallback_untraced
#include "../external/psp-recomp/src/rt/interp_runtime.cpp"
#undef sr_interpret_fallback

#include <cstdio>
#include <cstdlib>

extern "C" int sr_mgspo_trace_active(void);
extern "C" void sr_mgspo_trace_append(const char *body);

extern "C" int sr_interpret_fallback(
    CpuState *state, uint32_t target, uint32_t return_pc,
    uint64_t max_steps, int allow_native_handoff, SrInterpStop *stop) {
    ref::CpuState interpreted;
    import_state(&interpreted, state, target);
    ref::Memory memory(nullptr, read_runtime, write_runtime);
    uint32_t initial_target = target;

    std::FILE *trace_file = nullptr;
    ref::TraceSink *trace_sink = nullptr;
    if (sr_mgspo_trace_active()) {
        sr_end(state, 0, 0);
        trace_file = std::tmpfile();
        if (!trace_file) {
            std::fprintf(
                stderr,
                "interpreter: cannot create temporary trace stream\n");
            std::abort();
        }
        trace_sink = new ref::TraceSink(trace_file);
    }

    ref::StepResult result = ref::Run(
        &interpreted, &memory, max_steps, trace_sink, true, return_pc,
        allow_native_handoff ? has_native_target : nullptr,
        allow_native_handoff ? &initial_target : nullptr,
        execute_vfpu_fallback, nullptr,
        yield_runtime, state);
    export_state(state, &interpreted);

    if (trace_file) {
        delete trace_sink;
        if (std::fflush(trace_file) != 0 ||
            std::fseek(trace_file, 0, SEEK_SET) != 0) {
            std::fprintf(
                stderr,
                "interpreter: cannot rewind temporary trace stream\n");
            std::fclose(trace_file);
            std::abort();
        }
        auto append_line = [](char *line) {
            char *body = std::strchr(line, ' ');
            if (!body) {
                std::fprintf(
                    stderr,
                    "interpreter: malformed temporary trace line\n");
                std::abort();
            }
            body++;
            std::size_t length = std::strlen(body);
            while (length && (body[length - 1] == '\n' ||
                              body[length - 1] == '\r'))
                body[--length] = '\0';
            sr_mgspo_trace_append(body);
        };

        char line[8192];
        char pending[8192] = {};
        int have_pending = 0;
        while (std::fgets(line, sizeof(line), trace_file)) {
            if (have_pending)
                append_line(pending);
            std::memcpy(pending, line, sizeof(pending));
            have_pending = 1;
        }
        int read_error = std::ferror(trace_file);
        if (have_pending &&
            result.reason != ref::StopReason::kSyscall)
            append_line(pending);
        if (read_error || std::fclose(trace_file) != 0) {
            std::fprintf(
                stderr,
                "interpreter: cannot read temporary trace stream\n");
            std::abort();
        }
        if (result.reason == ref::StopReason::kSyscall)
            sr_begin(state, result.pc, result.op);
    }

    if (stop) {
        stop->reason = convert_reason(result.reason);
        stop->pc = result.pc;
        stop->op = result.op;
        stop->memory_address = memory.fault_addr();
        stop->steps = result.steps;
    }
    return result.reason == ref::StopReason::kTargetReached;
}

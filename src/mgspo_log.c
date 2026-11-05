#define _CRT_SECURE_NO_WARNINGS

#include "mgspo_log.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static FILE *s_log;
static uint64_t s_sequence;
static char s_category_filter[128];

static int category_name_valid(const char *name, size_t length) {
    static const char *names[] = {
        "runtime",
        "import",
        "syscall",
        "module",
        "thread",
        "file",
        "display_list",
        "fatal",
    };
    for (size_t index = 0;
         index < sizeof(names) / sizeof(names[0]);
         ++index)
        if (strlen(names[index]) == length &&
            strncmp(name, names[index], length) == 0) {
            return 1;
        }
    return 0;
}

static int category_filter_valid(const char *filter) {
    if (!filter || !filter[0]) return 1;
    const char *cursor = filter;
    while (cursor[0]) {
        const char *end = strchr(cursor, ',');
        size_t length =
            end ? (size_t)(end - cursor) : strlen(cursor);
        if (!length || !category_name_valid(cursor, length))
            return 0;
        if (!end) return 1;
        cursor = end + 1;
    }
    return 0;
}

static int category_enabled(const char *category) {
    if (!s_log) return 0;
    if (!s_category_filter[0]) return 1;
    const char *cursor = s_category_filter;
    size_t category_length = strlen(category);
    while (cursor[0]) {
        const char *end = strchr(cursor, ',');
        size_t length =
            end ? (size_t)(end - cursor) : strlen(cursor);
        if (length == category_length &&
            strncmp(cursor, category, length) == 0) {
            return 1;
        }
        cursor = end ? end + 1 : cursor + length;
    }
    return 0;
}

static void write_json_string(const char *value) {
    fputc('"', s_log);
    for (const unsigned char *cursor =
             (const unsigned char *)(value ? value : "");
         *cursor;
         ++cursor) {
        unsigned char character = *cursor;
        switch (character) {
        case '"':
            fputs("\\\"", s_log);
            break;
        case '\\':
            fputs("\\\\", s_log);
            break;
        case '\b':
            fputs("\\b", s_log);
            break;
        case '\f':
            fputs("\\f", s_log);
            break;
        case '\n':
            fputs("\\n", s_log);
            break;
        case '\r':
            fputs("\\r", s_log);
            break;
        case '\t':
            fputs("\\t", s_log);
            break;
        default:
            if (character < 0x20)
                fprintf(s_log, "\\u%04x", character);
            else
                fputc(character, s_log);
            break;
        }
    }
    fputc('"', s_log);
}

static void begin_event(const char *category, const char *event) {
    fprintf(s_log, "{\"sequence\":%llu,\"category\":",
            (unsigned long long)s_sequence++);
    write_json_string(category);
    fputs(",\"event\":", s_log);
    write_json_string(event);
}

static void end_event(void) {
    fputs("}\n", s_log);
}

int mgspo_log_open(const char *path) {
    if (s_log || !path || !path[0]) return 0;
    const char *category_filter = getenv("MGSPO_LOG_CATEGORIES");
    if (!category_filter_valid(category_filter) ||
        (category_filter &&
         strlen(category_filter) >= sizeof(s_category_filter))) {
        fprintf(
            stderr,
            "ERROR: MGSPO_LOG_CATEGORIES contains an invalid "
            "comma-separated category list.\n");
        return -1;
    }
    s_log = fopen(path, "wb");
    if (!s_log) return -1;
    if (setvbuf(s_log, NULL, _IONBF, 0) != 0) {
        fclose(s_log);
        s_log = NULL;
        return -1;
    }
    snprintf(
        s_category_filter,
        sizeof(s_category_filter),
        "%s",
        category_filter ? category_filter : "");
    s_sequence = 0;
    return 0;
}

void mgspo_log_close(void) {
    if (!s_log) return;
    fclose(s_log);
    s_log = NULL;
    s_category_filter[0] = 0;
}

int mgspo_log_is_open(void) {
    return s_log != NULL;
}

void mgspo_log_runtime(
    const char *level, const char *event, const char *message) {
    if (!category_enabled("runtime")) return;
    begin_event("runtime", event);
    fputs(",\"level\":", s_log);
    write_json_string(level);
    fputs(",\"message\":", s_log);
    write_json_string(message);
    end_event();
}

void mgspo_log_syscall(
    const char *phase,
    const char *library,
    const char *name,
    uint32_t nid,
    uint32_t thread_uid,
    uint32_t pc,
    const uint32_t arguments[4],
    uint32_t result) {
    const char *category =
        phase && strcmp(phase, "dispatch") == 0
        ? "import"
        : "syscall";
    if (!category_enabled(category)) return;
    begin_event(category, phase);
    fputs(",\"library\":", s_log);
    write_json_string(library);
    fputs(",\"name\":", s_log);
    write_json_string(name);
    fprintf(
        s_log,
        ",\"nid\":\"0x%08x\",\"thread_uid\":\"0x%x\","
        "\"pc\":\"0x%08x\",\"arguments\":["
        "\"0x%08x\",\"0x%08x\",\"0x%08x\",\"0x%08x\"],"
        "\"result\":\"0x%08x\"",
        nid,
        thread_uid,
        pc,
        arguments[0],
        arguments[1],
        arguments[2],
        arguments[3],
        result);
    end_event();
}

void mgspo_log_module(
    const char *path,
    uint32_t uid,
    uint32_t base,
    uint32_t size,
    uint32_t entry,
    uint32_t gp,
    uint32_t module_start,
    uint32_t module_stop,
    uint32_t start_priority,
    uint32_t start_stack_size,
    uint32_t start_attributes,
    uint32_t result) {
    if (!category_enabled("module")) return;
    begin_event("module", (int32_t)result < 0 ? "load_failed" : "loaded");
    fputs(",\"path\":", s_log);
    write_json_string(path);
    fprintf(
        s_log,
        ",\"uid\":\"0x%x\",\"base\":\"0x%08x\",\"size\":%u,"
        "\"entry\":\"0x%08x\",\"gp\":\"0x%08x\","
        "\"module_start\":\"0x%08x\",\"module_stop\":\"0x%08x\","
        "\"start_priority\":%u,\"start_stack_size\":%u,"
        "\"start_attributes\":\"0x%08x\","
        "\"result\":\"0x%08x\"",
        uid,
        base,
        size,
        entry,
        gp,
        module_start,
        module_stop,
        start_priority,
        start_stack_size,
        start_attributes,
        result);
    end_event();
}

void mgspo_log_module_callback(
    const char *event,
    const char *path,
    uint32_t uid,
    uint32_t entry,
    uint32_t gp,
    uint32_t argument_size,
    uint32_t argument_address,
    uint32_t status_address,
    uint32_t option_address,
    uint32_t status,
    uint32_t result) {
    if (!category_enabled("module")) return;
    begin_event("module", event);
    fputs(",\"path\":", s_log);
    write_json_string(path);
    fprintf(
        s_log,
        ",\"uid\":\"0x%x\",\"entry\":\"0x%08x\","
        "\"gp\":\"0x%08x\",\"argument_size\":%u,"
        "\"argument_address\":\"0x%08x\","
        "\"status_address\":\"0x%08x\","
        "\"option_address\":\"0x%08x\","
        "\"status\":\"0x%08x\",\"result\":\"0x%08x\"",
        uid,
        entry,
        gp,
        argument_size,
        argument_address,
        status_address,
        option_address,
        status,
        result);
    end_event();
}

void mgspo_log_module_unload(
    const char *path,
    uint32_t uid,
    uint32_t base,
    uint32_t size,
    uint32_t result) {
    if (!category_enabled("module")) return;
    begin_event("module", (int32_t)result < 0 ? "unload_failed" : "unloaded");
    fputs(",\"path\":", s_log);
    write_json_string(path);
    fprintf(
        s_log,
        ",\"uid\":\"0x%x\",\"base\":\"0x%08x\",\"size\":%u,"
        "\"result\":\"0x%08x\"",
        uid,
        base,
        size,
        result);
    end_event();
}

void mgspo_log_thread(
    const char *event,
    uint32_t uid,
    const char *name,
    uint32_t entry,
    int priority,
    uint32_t result) {
    if (!category_enabled("thread")) return;
    begin_event("thread", event);
    fprintf(s_log, ",\"uid\":\"0x%x\",\"name\":", uid);
    write_json_string(name);
    fprintf(
        s_log,
        ",\"entry\":\"0x%08x\",\"priority\":%d,\"result\":\"0x%08x\"",
        entry,
        priority,
        result);
    end_event();
}

void mgspo_log_thread_state(
    const char *event,
    uint32_t uid,
    const char *name,
    uint32_t entry,
    int priority,
    uint32_t stack_start,
    uint32_t stack_size,
    uint32_t attributes,
    uint32_t gp,
    uint32_t argument_size,
    uint32_t argument_address,
    uint32_t sp,
    uint32_t k0,
    uint32_t ra,
    uint32_t exit_status,
    uint32_t result) {
    if (!category_enabled("thread")) return;
    begin_event("thread", event);
    fprintf(s_log, ",\"uid\":\"0x%x\",\"name\":", uid);
    write_json_string(name);
    fprintf(
        s_log,
        ",\"entry\":\"0x%08x\",\"priority\":%d,"
        "\"stack_start\":\"0x%08x\",\"stack_size\":%u,"
        "\"attributes\":\"0x%08x\",\"gp\":\"0x%08x\","
        "\"argument_size\":%u,\"argument_address\":\"0x%08x\","
        "\"sp\":\"0x%08x\",\"k0\":\"0x%08x\",\"ra\":\"0x%08x\","
        "\"exit_status\":\"0x%08x\",\"result\":\"0x%08x\"",
        entry,
        priority,
        stack_start,
        stack_size,
        attributes,
        gp,
        argument_size,
        argument_address,
        sp,
        k0,
        ra,
        exit_status,
        result);
    end_event();
}

void mgspo_log_file_failure(
    const char *operation, const char *path, uint32_t result) {
    if (!category_enabled("file")) return;
    begin_event("file", "failure");
    fputs(",\"operation\":", s_log);
    write_json_string(operation);
    fputs(",\"path\":", s_log);
    write_json_string(path);
    fprintf(s_log, ",\"result\":\"0x%08x\"", result);
    end_event();
}

void mgspo_log_display_list(
    const char *operation,
    uint32_t thread_uid,
    const uint32_t arguments[4],
    uint32_t result) {
    if (!category_enabled("display_list")) return;
    begin_event("display_list", operation);
    fprintf(
        s_log,
        ",\"thread_uid\":\"0x%x\",\"arguments\":["
        "\"0x%08x\",\"0x%08x\",\"0x%08x\",\"0x%08x\"],"
        "\"result\":\"0x%08x\"",
        thread_uid,
        arguments[0],
        arguments[1],
        arguments[2],
        arguments[3],
        result);
    end_event();
}

void mgspo_log_fatal(
    const char *event, const char *message, uint32_t code, uint32_t pc) {
    if (!category_enabled("fatal")) return;
    begin_event("fatal", event);
    fputs(",\"message\":", s_log);
    write_json_string(message);
    fprintf(
        s_log, ",\"code\":\"0x%08x\",\"pc\":\"0x%08x\"", code, pc);
    end_event();
}

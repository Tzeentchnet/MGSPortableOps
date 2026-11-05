#ifndef MGSPO_LOG_H
#define MGSPO_LOG_H

#include <stdint.h>

int mgspo_log_open(const char *path);
void mgspo_log_close(void);
int mgspo_log_is_open(void);

void mgspo_log_runtime(
    const char *level, const char *event, const char *message);
void mgspo_log_syscall(
    const char *phase,
    const char *library,
    const char *name,
    uint32_t nid,
    uint32_t thread_uid,
    uint32_t pc,
    const uint32_t arguments[4],
    uint32_t result);
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
    uint32_t result);
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
    uint32_t result);
void mgspo_log_module_unload(
    const char *path,
    uint32_t uid,
    uint32_t base,
    uint32_t size,
    uint32_t result);
void mgspo_log_thread(
    const char *event,
    uint32_t uid,
    const char *name,
    uint32_t entry,
    int priority,
    uint32_t result);
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
    uint32_t result);
void mgspo_log_file_failure(
    const char *operation, const char *path, uint32_t result);
void mgspo_log_display_list(
    const char *operation,
    uint32_t thread_uid,
    const uint32_t arguments[4],
    uint32_t result);
void mgspo_log_fatal(
    const char *event, const char *message, uint32_t code, uint32_t pc);

#endif

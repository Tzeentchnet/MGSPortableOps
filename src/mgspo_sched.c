#include "../external/psp-recomp/src/rt/recomp.h"
#include "mgspo_log.h"
#include "mgspo_runtime_settings.h"

extern int g_mgspo_module_start_pending;

static void mgspo_sched_dispatch(CpuState *state, uint32_t address);
uint32_t mgspo_sched_start_thread_builtin(
    uint32_t uid, uint32_t argument_size, uint32_t argument_address);
uint32_t mgspo_sched_create_thread_builtin(
    const char *name,
    uint32_t entry,
    int priority,
    uint32_t stack_size,
    uint32_t attributes);
int mgspo_sched_delete_thread_builtin(uint32_t uid);
void mgspo_sched_exit_current_builtin(int32_t status);
void mgspo_sched_terminate_thread_builtin(uint32_t uid);
void mgspo_sched_exit_delete_current_builtin(int32_t status);

#define dispatch mgspo_sched_dispatch
#define sched_create_thread mgspo_sched_create_thread_builtin
#define sched_delete_thread mgspo_sched_delete_thread_builtin
#define sched_exit_current mgspo_sched_exit_current_builtin
#define sched_exit_delete_current mgspo_sched_exit_delete_current_builtin
#define sched_start_thread mgspo_sched_start_thread_builtin
#define sched_terminate_thread mgspo_sched_terminate_thread_builtin
#include "../external/psp-recomp/src/rt/sched.c"
#undef sched_terminate_thread
#undef sched_start_thread
#undef sched_exit_delete_current
#undef sched_exit_current
#undef sched_delete_thread
#undef sched_create_thread
#undef dispatch

static uint32_t s_mgspo_released_wait_uid[MAXTHREADS];

uint32_t mgspo_sched_release_wait_thread(uint32_t uid) {
    if (!uid || uid == sched_current_uid())
        return UINT32_C(0x80020197);

    TCB *thread = tcb_by_uid(uid);
    if (!thread) return UINT32_C(0x80020198);
    if (thread->state != TH_WAIT_DELAY &&
        thread->state != TH_WAIT_OBJ)
        return UINT32_C(0x800201a6);

    int index = (int)(thread - s_tcb);
    s_mgspo_released_wait_uid[index] = uid;
    thread->state = TH_READY;
    thread->sleeping = 0;
    thread->wait_obj = 0;
    thread->wake = 0;
    mgspo_log_thread(
        "wait_released",
        thread->uid,
        thread->name,
        thread->entry,
        thread->priority,
        0);
    return 0;
}

int mgspo_sched_consume_wait_release(void) {
    if (s_cur < 0) return 0;
    TCB *thread = &s_tcb[s_cur];
    if (s_mgspo_released_wait_uid[s_cur] != thread->uid)
        return 0;
    s_mgspo_released_wait_uid[s_cur] = 0;
    return 1;
}

static void mgspo_sched_dispatch(CpuState *state, uint32_t address) {
    dispatch(state, address);
    mgspo_runtime_settings_poll();
    if (s_intr_depth || s_cur < 0) return;

    sr_begin(state, UINT32_C(0x08000030), UINT32_C(0x03e00008));
    sr_end(state, 0, 0);

    CpuState returning = *state;
    TCB *current = &s_tcb[s_cur];
    int current_state = current->state;
    sched_wake(current->uid);
    current->state = TH_DORMANT;
    int next = pick_next();
    int next_waited_for_current =
        next >= 0 && s_tcb[next].wait_obj == current->uid;
    current->state = current_state;

    sr_begin(state, UINT32_C(0x08000034), UINT32_C(0x010c010c));
    if (next >= 0) {
        *state = s_tcb[next].saved;
        if (next_waited_for_current) {
            state->r[1] = UINT32_C(0xdeadbeef);
            for (int index = 4; index <= 15; ++index)
                state->r[index] = UINT32_C(0xdeadbeef);
            state->r[24] = UINT32_C(0xdeadbeef);
            state->r[25] = UINT32_C(0xdeadbeef);
            state->hi = UINT32_C(0xdeadbeef);
            state->lo = UINT32_C(0xdeadbeef);
        }
    }
    sr_end(state, 0, 0);
    *state = returning;
}

uint32_t sched_create_thread(
    const char *name,
    uint32_t entry,
    int priority,
    uint32_t stack_size,
    uint32_t attributes) {
    uint32_t result = mgspo_sched_create_thread_builtin(
        name, entry, priority, stack_size, attributes);
    TCB *thread =
        (int32_t)result < 0 ? NULL : tcb_by_uid(result);
    mgspo_log_thread_state(
        (int32_t)result < 0 ? "create_failed" : "created",
        (int32_t)result < 0 ? 0 : result,
        name,
        entry,
        priority,
        thread ? thread->stack_start : 0,
        thread ? thread->stack_size : stack_size,
        thread ? thread->attr : attributes,
        thread ? thread->gp : 0,
        0,
        0,
        0,
        0,
        0,
        thread ? (uint32_t)thread->exit_status : 0,
        result);
    return result;
}

uint32_t sched_start_thread(
    uint32_t uid, uint32_t argument_size, uint32_t argument_address) {
    uint32_t result = mgspo_sched_start_thread_builtin(
        uid, argument_size, argument_address);
    TCB *thread = tcb_by_uid(uid);
    if ((int32_t)result < 0 || !thread) {
        uint32_t logged_result =
            (int32_t)result < 0 ? result : UINT32_C(0x80020198);
        mgspo_log_thread_state(
            "start_failed",
            uid,
            thread ? thread->name : "",
            thread ? thread->entry : 0,
            thread ? thread->priority : 0,
            thread ? thread->stack_start : 0,
            thread ? thread->stack_size : 0,
            thread ? thread->attr : 0,
            thread ? thread->gp : 0,
            argument_size,
            argument_address,
            0,
            0,
            0,
            thread ? (uint32_t)thread->exit_status : 0,
            logged_result);
        return logged_result;
    }
    if (uid == MGSPO_NEXT_UID) {
        thread->saved.r[2] = 0;
        memset(thread->saved.vi, 0, sizeof(thread->saved.vi));
    }
    if (g_mgspo_module_start_pending) {
        thread->saved.r[31] = UINT32_C(0x08000030);
        g_mgspo_module_start_pending = 0;
    }
    mgspo_log_thread_state(
        "started",
        uid,
        thread->name,
        thread->entry,
        thread->priority,
        thread->stack_start,
        thread->stack_size,
        thread->attr,
        thread->gp,
        thread->arglen,
        thread->argp,
        thread->saved.r[29],
        thread->saved.r[26],
        thread->saved.r[31],
        (uint32_t)thread->exit_status,
        result);
    return result;
}

int sched_delete_thread(uint32_t uid) {
    TCB *thread = tcb_by_uid(uid);
    char name[sizeof(thread->name)];
    uint32_t entry = 0;
    int priority = 0;
    uint32_t stack_start = 0;
    uint32_t stack_size = 0;
    uint32_t attributes = 0;
    uint32_t gp = 0;
    uint32_t argument_size = 0;
    uint32_t argument_address = 0;
    uint32_t sp = 0;
    uint32_t k0 = 0;
    uint32_t ra = 0;
    uint32_t exit_status = 0;
    if (thread) {
        snprintf(name, sizeof(name), "%s", thread->name);
        entry = thread->entry;
        priority = thread->priority;
        stack_start = thread->stack_start;
        stack_size = thread->stack_size;
        attributes = thread->attr;
        gp = thread->gp;
        argument_size = thread->arglen;
        argument_address = thread->argp;
        sp = thread->saved.r[29];
        k0 = thread->saved.r[26];
        ra = thread->saved.r[31];
        exit_status = (uint32_t)thread->exit_status;
    } else {
        name[0] = 0;
    }
    int result = mgspo_sched_delete_thread_builtin(uid);
    mgspo_log_thread_state(
        result < 0 ? "delete_failed" : "deleted",
        uid,
        name,
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
        (uint32_t)result);
    return result;
}

void sched_exit_current(int32_t status) {
    TCB *thread = s_cur >= 0 ? &s_tcb[s_cur] : NULL;
    mgspo_log_thread(
        "exited",
        thread ? thread->uid : 0,
        thread ? thread->name : "",
        thread ? thread->entry : 0,
        thread ? thread->priority : 0,
        (uint32_t)status);
    mgspo_sched_exit_current_builtin(status);
}

void sched_terminate_thread(uint32_t uid) {
    TCB *thread = tcb_by_uid(uid);
    mgspo_log_thread(
        "terminated",
        uid,
        thread ? thread->name : "",
        thread ? thread->entry : 0,
        thread ? thread->priority : 0,
        0);
    mgspo_sched_terminate_thread_builtin(uid);
}

void sched_exit_delete_current(int32_t status) {
    if (s_cur < 0) return;
    TCB *thread = &s_tcb[s_cur];
    mgspo_log_thread(
        "exit_deleted",
        thread->uid,
        thread->name,
        thread->entry,
        thread->priority,
        (uint32_t)status);
    thread->exit_status = status;
    thread->state = TH_DORMANT;
    sched_wake(thread->uid);
    delete_tcb(thread, 1);

    int next = pick_next();
    if (next >= 0) *s_cpu = s_tcb[next].saved;
    sr_end(s_cpu, 0, 0);
    switch_to_scheduler();
}

uint32_t mgspo_sched_change_current_attr(
    uint32_t clear_attributes, uint32_t set_attributes) {
    const uint32_t vfpu_attribute = UINT32_C(0x00004000);
    if ((clear_attributes & ~vfpu_attribute) ||
        (set_attributes & ~vfpu_attribute))
        return UINT32_C(0x80020191);
    if (s_cur < 0) return UINT32_MAX;
    s_tcb[s_cur].attr =
        (s_tcb[s_cur].attr & ~clear_attributes) | set_attributes;
    return 0;
}

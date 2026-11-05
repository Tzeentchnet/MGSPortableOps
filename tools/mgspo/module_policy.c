#include "recomp.h"

#include "mgspo_boot_contract.h"

#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

extern const SrDispatchTable mgspo_zlib_dispatch_table;

static SrModulePolicyEntry s_mgspo_modules[] = {
    {
        "disc0:/PSP_GAME/USRDIR/modules/zlibdec.prx",
        "ZLIB",
        "518c64f39a7492340cdcc3411044d555a4faae8d",
        SR_MODULE_GUEST,
        UINT32_C(0x08b20000),
        &mgspo_zlib_dispatch_table,
    },
    {
        "disc0:/PSP_GAME/USRDIR/modules/libfont.prx",
        "*",
        "387b53118f50c254ae3068168dc0e48ac95f72f5",
        SR_MODULE_HLE,
        0,
        NULL,
    },
};

void sr_mgspo_register_core_hle_overrides(void);

void sr_mgspo_register_module_policy(void) {
    const char *native_zlib = getenv("MGSPO_ENABLE_NATIVE_ZLIB");
    if (native_zlib && strcmp(native_zlib, "0") == 0) {
        s_mgspo_modules[0].native_base = 0;
        s_mgspo_modules[0].native_dispatch = NULL;
    } else if (!native_zlib || !native_zlib[0] ||
               strcmp(native_zlib, "1") == 0) {
        s_mgspo_modules[0].native_base = UINT32_C(0x08b20000);
        s_mgspo_modules[0].native_dispatch = &mgspo_zlib_dispatch_table;
    } else {
        fprintf(
            stderr,
            "MGSPO_ENABLE_NATIVE_ZLIB: expected 0 or 1, got %s\n",
            native_zlib);
        abort();
    }
    sr_module_set_policy(
        s_mgspo_modules,
        (uint32_t)(sizeof(s_mgspo_modules) / sizeof(s_mgspo_modules[0])));
}

static uint32_t h_mgspo_current_clock_local(CpuState *state) {
    uint32_t output = state->r[4];
    if (!output || !sr_inrange(output) || !sr_inrange(output + 15)) {
        return UINT32_C(0x80000103);
    }
    MEM_W16(output + 0, MGSPO_RTC_YEAR);
    MEM_W16(output + 2, MGSPO_RTC_MONTH);
    MEM_W16(output + 4, MGSPO_RTC_DAY);
    MEM_W16(output + 6, MGSPO_RTC_HOUR);
    MEM_W16(output + 8, MGSPO_RTC_MINUTE);
    MEM_W16(output + 10, MGSPO_RTC_SECOND);
    MEM_W32(output + 12, 0);
    return 0;
}

static uint32_t h_mgspo_system_param_int(CpuState *state) {
    uint32_t id = state->r[4];
    uint32_t output = state->r[5];
    uint32_t value;
    switch (id) {
        case 2: value = 1; break;
        case 3: value = 0; break;
        case 4: value = 2; break;
        case 5: value = 0; break;
        case 6: value = 60; break;
        case 7: value = 0; break;
        case 8: value = 1; break;
        case 9: value = 1; break;
        case 10: value = 9; break;
        default: value = 0; break;
    }
    if (!output || !sr_inrange(output) || !sr_inrange(output + 3)) {
        return UINT32_C(0x80000103);
    }
    MEM_W32(output, value);
    return 0;
}

static uint32_t h_mgspo_open_psid(CpuState *state) {
    static const uint8_t psid[16] = {
        0x12, 0x34, 0x56, 0x78, 0x9a, 0xbc, 0x93, 0xb0,
        0xcc, 0x6e, 0xd1, 0x32, 0x27, 0x85, 0x0f, 0x9d,
    };
    uint32_t output = state->r[4];
    if (!output || !sr_inrange(output) || !sr_inrange(output + 15)) {
        return UINT32_C(0x80000103);
    }
    for (size_t index = 0; index < sizeof(psid); ++index)
        MEM_W8(output + (uint32_t)index, psid[index]);
    return 0;
}

static uint32_t h_mgspo_wlan_ether_addr(CpuState *state) {
    static const uint8_t address[6] = {
        0x12, 0x34, 0x56, 0x78, 0x9a, 0xbc,
    };
    uint32_t output = state->r[4];
    if (!output || !sr_inrange(output) || !sr_inrange(output + 5)) {
        return UINT32_C(0x80000103);
    }
    for (size_t index = 0; index < sizeof(address); ++index)
        MEM_W8(output + (uint32_t)index, address[index]);
    return 0;
}

static uint32_t h_mgspo_wlan_enabled(CpuState *state) {
    (void)state;
    return 1;
}

static uint32_t s_mgspo_interrupts_enabled = 1;

static uint32_t h_mgspo_cpu_suspend_intr(CpuState *state) {
    (void)state;
    uint32_t previous = s_mgspo_interrupts_enabled;
    s_mgspo_interrupts_enabled = 0;
    return previous;
}

static uint32_t h_mgspo_cpu_resume_intr(CpuState *state) {
    s_mgspo_interrupts_enabled = state->r[4] != 0;
    return state->r[2];
}

void sr_mgspo_register_hle_overrides(void) {
    sr_mgspo_register_core_hle_overrides();
    sr_hle_register(
        UINT32_C(0xe7c27d1b),
        "sceRtcGetCurrentClockLocalTime",
        h_mgspo_current_clock_local);
    sr_hle_register(
        UINT32_C(0xa5da2406),
        "sceUtilityGetSystemParamInt",
        h_mgspo_system_param_int);
    sr_hle_register(
        UINT32_C(0xc69bebce),
        "sceOpenPSIDGetOpenPSID",
        h_mgspo_open_psid);
    sr_hle_register(
        UINT32_C(0x0c622081),
        "sceWlanGetEtherAddr",
        h_mgspo_wlan_ether_addr);
    sr_hle_register(
        UINT32_C(0x93440b11),
        "sceWlanDevIsPowerOn",
        h_mgspo_wlan_enabled);
    sr_hle_register(
        UINT32_C(0xd7763699),
        "sceWlanGetSwitchState",
        h_mgspo_wlan_enabled);
    sr_hle_register(
        UINT32_C(0x5f10d406),
        "sceKernelCpuResumeIntr",
        h_mgspo_cpu_resume_intr);
    sr_hle_register(
        UINT32_C(0x092968f4),
        "sceKernelCpuSuspendIntr",
        h_mgspo_cpu_suspend_intr);
}

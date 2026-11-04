#include "recomp.h"

#include <stddef.h>

static const SrModulePolicyEntry s_mgspo_modules[] = {
    {
        "disc0:/PSP_GAME/USRDIR/modules/libfont.prx",
        "*",
        "387b53118f50c254ae3068168dc0e48ac95f72f5",
        SR_MODULE_HLE,
        0,
        NULL,
    },
};

void sr_mgspo_register_module_policy(void) {
    sr_module_set_policy(
        s_mgspo_modules,
        (uint32_t)(sizeof(s_mgspo_modules) / sizeof(s_mgspo_modules[0])));
}

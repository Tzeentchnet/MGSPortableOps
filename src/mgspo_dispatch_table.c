#define sr_interpreter_module sr_interpreter_module_builtin
#include "../external/psp-recomp/src/rt/dispatch_table.c"
#undef sr_interpreter_module

const char *mgspo_module_name_for_address(uint32_t address);

const char *sr_interpreter_module(uint32_t address) {
    const char *module = sr_interpreter_module_builtin(address);
    return module ? module : mgspo_module_name_for_address(address);
}

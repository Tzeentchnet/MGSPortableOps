#define sr_vfpu_interp sr_mgspo_vfpu_interp_builtin
#include "../external/psp-recomp/src/rt/vfpu_interp.c"
#undef sr_vfpu_interp

#include <stdio.h>

int sr_vfpu_interp(CpuState *state, uint32_t instruction) {
    int result =
        sr_mgspo_vfpu_interp_builtin(state, instruction);
    if (result != SR_VFPU_OTHER)
        return result;

    uint32_t opcode = instruction >> 26;
    int suboperation = (instruction >> 21) & 0x1f;
    int operation = (instruction >> 16) & 0x1f;
    if (opcode != 0x34)
        return SR_VFPU_OTHER;

    int size = vsize(instruction);
    int destination = instruction & 0x7f;
    int source = (instruction >> 8) & 0x7f;
    uint8_t destination_indices[4];
    uint8_t source_indices[4];
    float source_values[4];
    float results[4];
    vreg_idx(destination, size, destination_indices);
    vreg_idx(source, size, source_indices);

    if (suboperation == 0 && operation == 23) {
        sr_vread(
            source_values,
            state,
            source_indices,
            size,
            state->vfpuCtrl[0]);
        for (int index = 0; index < size; ++index)
            results[index] = sr_vfpu_asin(source_values[index]);
    } else if (suboperation == 2 && operation == 10) {
        float zero_values[4];
        uint32_t zero_prefix =
            (state->vfpuCtrl[1] & ~UINT32_C(0xff)) |
            UINT32_C(0xf000);
        sr_vread(
            source_values,
            state,
            source_indices,
            size,
            state->vfpuCtrl[0]);
        sr_vread(
            zero_values,
            state,
            source_indices,
            size,
            zero_prefix);
        for (int index = 0; index < size; ++index) {
            float difference =
                source_values[index] - zero_values[index];
            uint32_t bits;
            memcpy(&bits, &difference, sizeof(bits));
            results[index] =
                bits == 0 || bits == UINT32_C(0x80000000)
                    ? 0.0f
                    : (bits >> 31 ? -1.0f : 1.0f);
        }
    } else {
        return SR_VFPU_OTHER;
    }

    sr_vwrite(
        state,
        destination_indices,
        results,
        size,
        state->vfpuCtrl[2]);
    eat_prefix(state);
    return SR_VFPU_COMPUTE;
}

int mgspo_vfpu_verify_contract(void) {
    const uint32_t asin_instruction = UINT32_C(0xd0176060);
    const uint32_t sign_instruction = UINT32_C(0xd04a0080);
    CpuState state;
    memset(&state, 0, sizeof(state));
    state.vfpuCtrl[0] = UINT32_C(0xe4);
    state.vfpuCtrl[1] = UINT32_C(0xe4);

    uint8_t indices[1];
    int source = (asin_instruction >> 8) & 0x7f;
    vreg_idx(source, 1, indices);
    state.v[indices[0]] = 0.5f;
    int result = sr_vfpu_interp(&state, asin_instruction);
    float expected = sr_vfpu_asin(0.5f);
    int valid =
        result == SR_VFPU_COMPUTE &&
        memcmp(
            &state.v[indices[0]],
            &expected,
            sizeof(expected)) == 0 &&
        state.vfpuCtrl[0] == UINT32_C(0xe4) &&
        state.vfpuCtrl[1] == UINT32_C(0xe4) &&
        state.vfpuCtrl[2] == 0;

    memset(&state, 0, sizeof(state));
    state.vfpuCtrl[0] = UINT32_C(0xe4);
    state.vfpuCtrl[1] = UINT32_C(0xe4);
    uint8_t sign_indices[2];
    vreg_idx(0, 2, sign_indices);
    state.v[sign_indices[0]] = -0.5f;
    state.v[sign_indices[1]] = 0.0f;
    valid =
        valid &&
        sr_vfpu_interp(&state, sign_instruction) ==
            SR_VFPU_COMPUTE &&
        state.v[sign_indices[0]] == -1.0f &&
        state.v[sign_indices[1]] == 0.0f;
    if (!valid) {
        fprintf(
            stderr,
            "ERROR: VFPU vasin/vsgn contract mismatch.\n");
        return 0;
    }
    return 1;
}

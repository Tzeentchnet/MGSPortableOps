#define sr_osk_input sr_osk_input_builtin
#include "../external/psp-recomp/src/rt/osk_win.c"
#undef sr_osk_input

#include <stdio.h>
#include <stdlib.h>

int sr_osk_input(
    const WCHAR *description,
    const WCHAR *initial,
    WCHAR *output,
    int capacity) {
    const char *scripted = getenv("MGSPO_OSK_TEXT");
    if (!scripted) {
        return sr_osk_input_builtin(
            description, initial, output, capacity);
    }

    int required = MultiByteToWideChar(
        CP_UTF8, MB_ERR_INVALID_CHARS, scripted, -1, NULL, 0);
    if (!required || required > capacity ||
        !MultiByteToWideChar(
            CP_UTF8,
            MB_ERR_INVALID_CHARS,
            scripted,
            -1,
            output,
            capacity)) {
        fprintf(
            stderr,
            "MGSPO_OSK_TEXT must be valid UTF-8 and fit in the "
            "%d-character OSK field\n",
            capacity > 0 ? capacity - 1 : 0);
        _Exit(2);
    }

    fprintf(stderr, "OSK: accepted scripted text from MGSPO_OSK_TEXT\n");
    return 1;
}

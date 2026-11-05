#ifndef _CRT_SECURE_NO_WARNINGS
#define _CRT_SECURE_NO_WARNINGS
#endif

#include "mgspo_runtime_settings.h"

#include "graphics_config.h"
#include "graphics_settings.h"
#include "input_settings.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>
#include <windows.h>

#define IDC_GRAPHICS_SETTINGS 1801
#define IDC_INPUT_SETTINGS 1802
#define IDC_RESTART_GAME 1803
#define IDC_RESTART_STATUS 1804

typedef struct RuntimeSettingsContext {
    int restart_required;
} RuntimeSettingsContext;

#pragma pack(push, 2)
typedef struct EmptyDialogTemplate {
    DLGTEMPLATE dialog;
    WORD menu;
    WORD window_class;
    WCHAR title;
} EmptyDialogTemplate;
#pragma pack(pop)

static int s_enabled;
static int s_f1_down;
static unsigned s_poll_divider;
static int s_active_graphics_valid;
static SrGraphicsConfig s_active_graphics;

static void set_control_font(HWND control) {
    SendMessage(
        control, WM_SETFONT,
        (WPARAM)GetStockObject(DEFAULT_GUI_FONT), TRUE);
}

static HWND add_control(
    HWND dialog,
    const char *class_name,
    const char *text,
    DWORD style,
    int x,
    int y,
    int width,
    int height,
    int identifier) {
    HWND control = CreateWindowExA(
        0, class_name, text, WS_CHILD | WS_VISIBLE | style,
        x, y, width, height, dialog,
        (HMENU)(INT_PTR)identifier, GetModuleHandleA(NULL), NULL);
    if (control) set_control_font(control);
    return control;
}

static void center_dialog(HWND dialog) {
    RECT bounds;
    int width;
    int height;
    GetWindowRect(dialog, &bounds);
    width = bounds.right - bounds.left;
    height = bounds.bottom - bounds.top;
    SetWindowPos(
        dialog, NULL,
        (GetSystemMetrics(SM_CXSCREEN) - width) / 2,
        (GetSystemMetrics(SM_CYSCREEN) - height) / 2,
        0, 0, SWP_NOSIZE | SWP_NOZORDER);
}

static int graphics_equal(
    const SrGraphicsConfig *left,
    const SrGraphicsConfig *right) {
    return left->renderer == right->renderer &&
           left->internal_resolution == right->internal_resolution &&
           left->texture_scale == right->texture_scale &&
           left->d3d12_full_rate == right->d3d12_full_rate &&
           left->anti_aliasing == right->anti_aliasing &&
           left->skip_startup == right->skip_startup;
}

static int restart_required(void) {
    const SrGraphicsConfig *current = sr_graphics_config_get();
    return s_active_graphics_valid && current &&
           !graphics_equal(&s_active_graphics, current);
}

static void update_restart_controls(
    HWND dialog, RuntimeSettingsContext *context) {
    context->restart_required = restart_required();
    SetDlgItemTextA(
        dialog, IDC_RESTART_STATUS,
        context->restart_required
            ? "Graphics changes are saved and will apply after restarting."
            : "Controller changes apply immediately. Graphics changes require a restart.");
    EnableWindow(
        GetDlgItem(dialog, IDC_RESTART_GAME),
        context->restart_required);
}

static int restart_process(HWND owner) {
    STARTUPINFOW startup;
    PROCESS_INFORMATION process;
    WCHAR executable[MAX_PATH];
    WCHAR directory[MAX_PATH];
    WCHAR *command_line;
    WCHAR *separator;
    DWORD length;

    length = GetModuleFileNameW(NULL, executable, MAX_PATH);
    if (!length || length >= MAX_PATH) {
        MessageBoxA(
            owner, "Cannot locate the current executable.",
            "Cannot Restart", MB_OK | MB_ICONERROR);
        return 0;
    }
    command_line = _wcsdup(GetCommandLineW());
    if (!command_line) {
        MessageBoxA(
            owner, "Cannot allocate the restart command line.",
            "Cannot Restart", MB_OK | MB_ICONERROR);
        return 0;
    }
    wcscpy(directory, executable);
    separator = wcsrchr(directory, L'\\');
    if (separator) *separator = 0;

    memset(&startup, 0, sizeof(startup));
    memset(&process, 0, sizeof(process));
    startup.cb = sizeof(startup);
    if (!CreateProcessW(
            executable,
            command_line,
            NULL,
            NULL,
            FALSE,
            0,
            NULL,
            directory,
            &startup,
            &process)) {
        char message[160];
        snprintf(
            message, sizeof(message),
            "Cannot restart the game (Windows error %lu).",
            (unsigned long)GetLastError());
        free(command_line);
        MessageBoxA(
            owner, message, "Cannot Restart",
            MB_OK | MB_ICONERROR);
        return 0;
    }
    free(command_line);
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    ExitProcess(0);
    return 1;
}

static INT_PTR CALLBACK runtime_settings_proc(
    HWND dialog, UINT message, WPARAM wparam, LPARAM lparam) {
    RuntimeSettingsContext *context =
        (RuntimeSettingsContext *)GetWindowLongPtr(
            dialog, GWLP_USERDATA);
    if (message == WM_INITDIALOG) {
        context = (RuntimeSettingsContext *)lparam;
        SetWindowLongPtr(
            dialog, GWLP_USERDATA, (LONG_PTR)context);
        SetWindowTextA(
            dialog, "Metal Gear Solid: Portable Ops Settings");
        add_control(
            dialog, "STATIC",
            "The game is paused while this window is open.",
            0, 16, 16, 330, 20, 0);
        add_control(
            dialog, "BUTTON", "Graphics...",
            WS_TABSTOP | BS_PUSHBUTTON,
            16, 48, 150, 34, IDC_GRAPHICS_SETTINGS);
        add_control(
            dialog, "BUTTON", "Controls...",
            WS_TABSTOP | BS_PUSHBUTTON,
            180, 48, 150, 34, IDC_INPUT_SETTINGS);
        add_control(
            dialog, "STATIC", "",
            0, 16, 98, 314, 38, IDC_RESTART_STATUS);
        add_control(
            dialog, "BUTTON", "Restart Now",
            WS_TABSTOP | BS_PUSHBUTTON,
            98, 146, 110, 30, IDC_RESTART_GAME);
        add_control(
            dialog, "BUTTON", "Resume",
            WS_TABSTOP | BS_DEFPUSHBUTTON,
            220, 146, 110, 30, IDOK);
        update_restart_controls(dialog, context);
        center_dialog(dialog);
        return TRUE;
    }
    if (message == WM_COMMAND && context) {
        int command = LOWORD(wparam);
        if (command == IDC_GRAPHICS_SETTINGS) {
            int result = sr_graphics_settings_show(
                "Metal Gear Solid: Portable Ops Graphics");
            if (result < 0) {
                MessageBoxA(
                    dialog,
                    "The graphics settings window could not be opened.",
                    "Settings Error", MB_OK | MB_ICONERROR);
            }
            update_restart_controls(dialog, context);
            return TRUE;
        }
        if (command == IDC_INPUT_SETTINGS) {
            int result = sr_input_settings_show(
                "Metal Gear Solid: Portable Ops Controls", 0);
            if (result < 0) {
                MessageBoxA(
                    dialog,
                    "The controller settings window could not be opened.",
                    "Settings Error", MB_OK | MB_ICONERROR);
            }
            return TRUE;
        }
        if (command == IDC_RESTART_GAME) {
            if (context->restart_required) restart_process(dialog);
            return TRUE;
        }
        if (command == IDOK || command == IDCANCEL) {
            EndDialog(dialog, IDOK);
            return TRUE;
        }
    }
    if (message == WM_CLOSE) {
        EndDialog(dialog, IDOK);
        return TRUE;
    }
    return FALSE;
}

int mgspo_runtime_settings_show(void) {
    RuntimeSettingsContext context;
    EmptyDialogTemplate dialog_template;
    INT_PTR result;

    if (!s_enabled) return 0;
    memset(&context, 0, sizeof(context));
    memset(&dialog_template, 0, sizeof(dialog_template));
    dialog_template.dialog.style =
        WS_POPUP | WS_CAPTION | WS_SYSMENU |
        DS_MODALFRAME | DS_CENTER;
    dialog_template.dialog.cx = 232;
    dialog_template.dialog.cy = 132;
    result = DialogBoxIndirectParamW(
        GetModuleHandleW(NULL),
        &dialog_template.dialog,
        NULL,
        runtime_settings_proc,
        (LPARAM)&context);
    if (result == -1) {
        fprintf(
            stderr,
            "settings: cannot open runtime settings dialog (error %lu)\n",
            (unsigned long)GetLastError());
        return -1;
    }
    return 1;
}

void mgspo_runtime_settings_enable(void) {
    const SrGraphicsConfig *graphics = sr_graphics_config_get();
    s_enabled = 1;
    s_f1_down = 0;
    s_poll_divider = 0;
    s_active_graphics_valid = graphics != NULL;
    if (graphics) s_active_graphics = *graphics;
    fprintf(stderr, "settings: press F1 to open runtime settings\n");
}

void mgspo_runtime_settings_poll(void) {
    HWND foreground;
    DWORD process_id = 0;
    SHORT f1_state;
    int f1_down;
    int f1_pressed;

    if (!s_enabled || (++s_poll_divider & 63u) != 0) return;
    f1_state = GetAsyncKeyState(VK_F1);
    f1_down = (f1_state & 0x8000) != 0;
    f1_pressed = (f1_state & 1) != 0;
    foreground = GetForegroundWindow();
    if (foreground)
        GetWindowThreadProcessId(foreground, &process_id);
    if ((f1_pressed || (f1_down && !s_f1_down)) &&
        process_id == GetCurrentProcessId()) {
        mgspo_runtime_settings_show();
        f1_down = (GetAsyncKeyState(VK_F1) & 0x8000) != 0;
    }
    s_f1_down = f1_down;
}

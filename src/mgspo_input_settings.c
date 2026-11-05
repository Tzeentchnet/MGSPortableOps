#ifndef _CRT_SECURE_NO_WARNINGS
#define _CRT_SECURE_NO_WARNINGS
#endif

#include "input_settings.h"

#include "input_config.h"

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>

#define IDC_DEVICE 2000
#define IDC_BINDING_EDIT_BASE 2100
#define IDC_CAPTURE_BASE 2200
#define IDC_RESET_DEFAULTS 2300
#define IDC_LAUNCH_GAME 2301
#define IDC_SAVE_STATUS 2302

#define IDC_RESPONSE_BASE 2400
#define IDC_ANALOG_DEADZONE 2400
#define IDC_ANALOG_CURVE 2401
#define IDC_ANALOG_INVERT_Y 2402
#define IDC_TWIN_STICK 2403
#define IDC_MOVEMENT_DEADZONE 2404
#define IDC_MOVEMENT_CURVE 2405
#define IDC_MOVEMENT_INVERT_Y 2406
#define IDC_AIM_DEADZONE 2407
#define IDC_AIM_CURVE 2408
#define IDC_AIM_INVERT_X 2409
#define IDC_AIM_INVERT_Y 2410
#define IDC_RESPONSE_LAST IDC_AIM_INVERT_Y
#define IDC_RESPONSE_LABEL_BASE 2450

#define INPUT_ROWS 16
#define BINDING_TEXT_SIZE 128

enum InputPage {
    INPUT_PAGE_KEYBOARD,
    INPUT_PAGE_MOUSE,
    INPUT_PAGE_GAMEPAD,
    INPUT_PAGE_RESPONSE,
};

enum CaptureDevice {
    CAPTURE_KEYBOARD,
    CAPTURE_MOUSE,
    CAPTURE_GAMEPAD,
};

typedef struct BindingName {
    int value;
    const char *name;
} BindingName;

typedef struct InputDialogContext {
    SrInputConfig config;
    const char *title;
    int allow_launch;
    int page;
    char keyboard[INPUT_ROWS][BINDING_TEXT_SIZE];
    char mouse[SR_INPUT_ACTIONS][BINDING_TEXT_SIZE];
    char gamepad[SR_INPUT_ACTIONS][BINDING_TEXT_SIZE];
} InputDialogContext;

typedef struct XInputGamepad {
    WORD buttons;
    BYTE left_trigger;
    BYTE right_trigger;
    SHORT left_x;
    SHORT left_y;
    SHORT right_x;
    SHORT right_y;
} XInputGamepad;

typedef struct XInputState {
    DWORD packet_number;
    XInputGamepad gamepad;
} XInputState;

typedef DWORD(WINAPI *XInputGetStateFn)(DWORD, XInputState *);

typedef struct CaptureContext {
    int device;
    char value[32];
    HMODULE xinput_module;
    XInputGetStateFn xinput_get_state;
    DWORD controller_index;
    WORD blocked_buttons;
    int blocked_left_trigger;
    int blocked_right_trigger;
    int controller_found;
} CaptureContext;

#pragma pack(push, 2)
typedef struct EmptyDialogTemplate {
    DLGTEMPLATE dialog;
    WORD menu;
    WORD window_class;
    WCHAR title;
} EmptyDialogTemplate;
#pragma pack(pop)

static const char *const s_action_names[SR_INPUT_ACTIONS] = {
    "select", "start", "up", "right", "down", "left",
    "l", "r", "triangle", "circle", "cross", "square",
};

static const char *const s_action_labels[SR_INPUT_ACTIONS] = {
    "Select", "Start", "D-pad Up", "D-pad Right", "D-pad Down", "D-pad Left",
    "L button", "R button", "Triangle", "Circle", "Cross", "Square",
};

static const char *const s_analog_names[SR_INPUT_ANALOG_DIRECTIONS] = {
    "analog_up", "analog_right", "analog_down", "analog_left",
};

static const char *const s_analog_labels[SR_INPUT_ANALOG_DIRECTIONS] = {
    "Analog Up", "Analog Right", "Analog Down", "Analog Left",
};

static const BindingName s_key_names[] = {
    {SR_KEY_ENTER, "enter"},
    {SR_KEY_LEFT_SHIFT, "left_shift"},
    {SR_KEY_RIGHT_SHIFT, "right_shift"},
    {SR_KEY_UP, "up"},
    {SR_KEY_RIGHT, "right"},
    {SR_KEY_DOWN, "down"},
    {SR_KEY_LEFT, "left"},
    {SR_KEY_SPACE, "space"},
    {SR_KEY_TAB, "tab"},
    {SR_KEY_BACKSPACE, "backspace"},
    {SR_KEY_LEFT_CTRL, "left_ctrl"},
    {SR_KEY_RIGHT_CTRL, "right_ctrl"},
};

static const BindingName s_mouse_names[] = {
    {SR_MOUSE_LEFT, "left"},
    {SR_MOUSE_RIGHT, "right"},
    {SR_MOUSE_MIDDLE, "middle"},
    {SR_MOUSE_X1, "x1"},
    {SR_MOUSE_X2, "x2"},
};

static const BindingName s_gamepad_names[] = {
    {SR_PAD_SOUTH, "south"},
    {SR_PAD_EAST, "east"},
    {SR_PAD_WEST, "west"},
    {SR_PAD_NORTH, "north"},
    {SR_PAD_START, "start"},
    {SR_PAD_BACK, "back"},
    {SR_PAD_LEFT_SHOULDER, "left_shoulder"},
    {SR_PAD_RIGHT_SHOULDER, "right_shoulder"},
    {SR_PAD_LEFT_TRIGGER, "left_trigger"},
    {SR_PAD_RIGHT_TRIGGER, "right_trigger"},
    {SR_PAD_DPAD_UP, "dpad_up"},
    {SR_PAD_DPAD_RIGHT, "dpad_right"},
    {SR_PAD_DPAD_DOWN, "dpad_down"},
    {SR_PAD_DPAD_LEFT, "dpad_left"},
    {SR_PAD_LEFT_STICK, "left_stick"},
    {SR_PAD_RIGHT_STICK, "right_stick"},
};

static void set_control_font(HWND control) {
    SendMessage(
        control, WM_SETFONT,
        (WPARAM)GetStockObject(DEFAULT_GUI_FONT), TRUE);
}

static HWND add_control(
    HWND dialog,
    DWORD extended_style,
    const char *class_name,
    const char *text,
    DWORD style,
    int x,
    int y,
    int width,
    int height,
    int identifier) {
    HWND control = CreateWindowExA(
        extended_style, class_name, text,
        WS_CHILD | WS_VISIBLE | style,
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

static int append_text(
    char *text, size_t text_size, size_t *used,
    const char *format, ...) {
    va_list arguments;
    int written;
    if (*used >= text_size) return 0;
    va_start(arguments, format);
    written = vsnprintf(
        text + *used, text_size - *used, format, arguments);
    va_end(arguments);
    if (written < 0 || (size_t)written >= text_size - *used) return 0;
    *used += (size_t)written;
    return 1;
}

static const char *binding_name(
    const BindingName *names, size_t count, int value,
    char single_character[2]) {
    size_t index;
    for (index = 0; index < count; ++index)
        if (names[index].value == value) return names[index].name;
    if (value >= 'A' && value <= 'Z') {
        single_character[0] = (char)value;
        single_character[1] = 0;
        return single_character;
    }
    if (value >= '0' && value <= '9') {
        single_character[0] = (char)value;
        single_character[1] = 0;
        return single_character;
    }
    return NULL;
}

static int format_binding(
    const SrInputBinding *binding,
    const BindingName *names,
    size_t name_count,
    char *text,
    size_t text_size) {
    size_t used = 0;
    int index;
    if (!text || !text_size) return 0;
    if (!binding->count) {
        if (text_size < sizeof("none")) return 0;
        strcpy(text, "none");
        return 1;
    }
    text[0] = 0;
    for (index = 0; index < binding->count; ++index) {
        char single_character[2];
        const char *name = binding_name(
            names, name_count, binding->values[index],
            single_character);
        size_t length;
        if (!name) return 0;
        length = strlen(name);
        if (used + (index ? 2u : 0u) + length + 1u > text_size)
            return 0;
        if (index) {
            memcpy(text + used, ", ", 2);
            used += 2;
        }
        memcpy(text + used, name, length);
        used += length;
        text[used] = 0;
    }
    return 1;
}

static void load_binding_texts(InputDialogContext *context) {
    int index;
    for (index = 0; index < SR_INPUT_ACTIONS; ++index) {
        format_binding(
            &context->config.keyboard[index],
            s_key_names, sizeof(s_key_names) / sizeof(s_key_names[0]),
            context->keyboard[index], BINDING_TEXT_SIZE);
        format_binding(
            &context->config.mouse[index],
            s_mouse_names,
            sizeof(s_mouse_names) / sizeof(s_mouse_names[0]),
            context->mouse[index], BINDING_TEXT_SIZE);
        format_binding(
            &context->config.gamepad[index],
            s_gamepad_names,
            sizeof(s_gamepad_names) / sizeof(s_gamepad_names[0]),
            context->gamepad[index], BINDING_TEXT_SIZE);
    }
    for (index = 0; index < SR_INPUT_ANALOG_DIRECTIONS; ++index) {
        format_binding(
            &context->config.analog_keyboard[index],
            s_key_names, sizeof(s_key_names) / sizeof(s_key_names[0]),
            context->keyboard[SR_INPUT_ACTIONS + index],
            BINDING_TEXT_SIZE);
    }
}

static void set_numeric_control(
    HWND dialog, int identifier, double value) {
    char text[32];
    snprintf(text, sizeof(text), "%.6g", value);
    SetDlgItemTextA(dialog, identifier, text);
}

static void load_response_controls(
    HWND dialog, const SrInputConfig *config) {
    set_numeric_control(dialog, IDC_ANALOG_DEADZONE, config->deadzone);
    set_numeric_control(dialog, IDC_ANALOG_CURVE, config->curve);
    set_numeric_control(
        dialog, IDC_MOVEMENT_DEADZONE, config->movement_deadzone);
    set_numeric_control(
        dialog, IDC_MOVEMENT_CURVE, config->movement_curve);
    set_numeric_control(dialog, IDC_AIM_DEADZONE, config->aim_deadzone);
    set_numeric_control(dialog, IDC_AIM_CURVE, config->aim_curve);
    CheckDlgButton(
        dialog, IDC_ANALOG_INVERT_Y,
        config->invert_y ? BST_CHECKED : BST_UNCHECKED);
    CheckDlgButton(
        dialog, IDC_TWIN_STICK,
        config->twin_stick_enabled ? BST_CHECKED : BST_UNCHECKED);
    CheckDlgButton(
        dialog, IDC_MOVEMENT_INVERT_Y,
        config->movement_invert_y ? BST_CHECKED : BST_UNCHECKED);
    CheckDlgButton(
        dialog, IDC_AIM_INVERT_X,
        config->aim_invert_x ? BST_CHECKED : BST_UNCHECKED);
    CheckDlgButton(
        dialog, IDC_AIM_INVERT_Y,
        config->aim_invert_y ? BST_CHECKED : BST_UNCHECKED);
}

static int page_row_count(int page) {
    return page == INPUT_PAGE_KEYBOARD
        ? INPUT_ROWS
        : page == INPUT_PAGE_RESPONSE ? 0 : SR_INPUT_ACTIONS;
}

static char *page_binding(InputDialogContext *context, int row) {
    if (context->page == INPUT_PAGE_KEYBOARD)
        return context->keyboard[row];
    if (context->page == INPUT_PAGE_MOUSE)
        return context->mouse[row];
    return context->gamepad[row];
}

static const char *page_label(int page, int row) {
    if (page == INPUT_PAGE_KEYBOARD && row >= SR_INPUT_ACTIONS)
        return s_analog_labels[row - SR_INPUT_ACTIONS];
    return s_action_labels[row];
}

static void store_current_page(
    HWND dialog, InputDialogContext *context) {
    int rows = page_row_count(context->page);
    int row;
    for (row = 0; row < rows; ++row) {
        char *binding = page_binding(context, row);
        GetDlgItemTextA(
            dialog, IDC_BINDING_EDIT_BASE + row,
            binding, BINDING_TEXT_SIZE);
        if (!binding[0]) strcpy(binding, "none");
    }
}

static void show_page(
    HWND dialog, InputDialogContext *context, int page) {
    int row;
    int rows;
    context->page = page;
    rows = page_row_count(page);
    for (row = 0; row < INPUT_ROWS; ++row) {
        int visible = row < rows;
        HWND label = GetDlgItem(
            dialog, IDC_RESPONSE_LABEL_BASE + 32 + row);
        HWND edit = GetDlgItem(dialog, IDC_BINDING_EDIT_BASE + row);
        HWND capture = GetDlgItem(dialog, IDC_CAPTURE_BASE + row);
        ShowWindow(label, visible ? SW_SHOW : SW_HIDE);
        ShowWindow(edit, visible ? SW_SHOW : SW_HIDE);
        ShowWindow(capture, visible ? SW_SHOW : SW_HIDE);
        if (visible) {
            SetWindowTextA(label, page_label(page, row));
            SetWindowTextA(edit, page_binding(context, row));
        }
    }
    for (row = IDC_RESPONSE_BASE; row <= IDC_RESPONSE_LAST; ++row)
        ShowWindow(
            GetDlgItem(dialog, row),
            page == INPUT_PAGE_RESPONSE ? SW_SHOW : SW_HIDE);
    for (row = 0; row <= 10; ++row)
        ShowWindow(
            GetDlgItem(dialog, IDC_RESPONSE_LABEL_BASE + row),
            page == INPUT_PAGE_RESPONSE ? SW_SHOW : SW_HIDE);
}

static const char *key_name_from_message(
    WPARAM wparam, LPARAM lparam) {
    static char character[2];
    if (wparam >= 'A' && wparam <= 'Z') {
        character[0] = (char)wparam;
        character[1] = 0;
        return character;
    }
    if (wparam >= '0' && wparam <= '9') {
        character[0] = (char)wparam;
        character[1] = 0;
        return character;
    }
    switch (wparam) {
        case VK_RETURN: return "enter";
        case VK_UP: return "up";
        case VK_RIGHT: return "right";
        case VK_DOWN: return "down";
        case VK_LEFT: return "left";
        case VK_SPACE: return "space";
        case VK_TAB: return "tab";
        case VK_BACK: return "backspace";
        case VK_SHIFT: {
            UINT scan = (UINT)((lparam >> 16) & 0xff);
            UINT left_scan = MapVirtualKeyA(
                VK_LSHIFT, MAPVK_VK_TO_VSC);
            return scan == left_scan
                ? "left_shift" : "right_shift";
        }
        case VK_CONTROL:
            return (lparam & (1u << 24))
                ? "right_ctrl" : "left_ctrl";
        default:
            return NULL;
    }
}

static void capture_complete(
    HWND dialog, CaptureContext *context, const char *value) {
    snprintf(context->value, sizeof(context->value), "%s", value);
    context->value[sizeof(context->value) - 1u] = 0;
    EndDialog(dialog, IDOK);
}

static const char *xinput_button_name(WORD buttons) {
    if (buttons & 0x1000) return "south";
    if (buttons & 0x2000) return "east";
    if (buttons & 0x4000) return "west";
    if (buttons & 0x8000) return "north";
    if (buttons & 0x0010) return "start";
    if (buttons & 0x0020) return "back";
    if (buttons & 0x0100) return "left_shoulder";
    if (buttons & 0x0200) return "right_shoulder";
    if (buttons & 0x0001) return "dpad_up";
    if (buttons & 0x0008) return "dpad_right";
    if (buttons & 0x0002) return "dpad_down";
    if (buttons & 0x0004) return "dpad_left";
    if (buttons & 0x0040) return "left_stick";
    if (buttons & 0x0080) return "right_stick";
    return NULL;
}

static void load_xinput(CaptureContext *context) {
    static const char *const libraries[] = {
        "xinput1_4.dll", "xinput1_3.dll", "xinput9_1_0.dll",
    };
    size_t index;
    for (index = 0;
         index < sizeof(libraries) / sizeof(libraries[0]);
         ++index) {
        context->xinput_module = LoadLibraryA(libraries[index]);
        if (!context->xinput_module) continue;
        context->xinput_get_state =
            (XInputGetStateFn)(void *)GetProcAddress(
                context->xinput_module, "XInputGetState");
        if (context->xinput_get_state) return;
        FreeLibrary(context->xinput_module);
        context->xinput_module = NULL;
    }
}

static int find_xinput_controller(
    CaptureContext *context, XInputState *state) {
    DWORD index;
    if (!context->xinput_get_state) return 0;
    for (index = 0; index < 4; ++index) {
        memset(state, 0, sizeof(*state));
        if (context->xinput_get_state(index, state) == ERROR_SUCCESS) {
            context->controller_index = index;
            context->blocked_buttons = state->gamepad.buttons;
            context->blocked_left_trigger =
                state->gamepad.left_trigger > 30;
            context->blocked_right_trigger =
                state->gamepad.right_trigger > 30;
            context->controller_found = 1;
            return 1;
        }
    }
    return 0;
}

static INT_PTR CALLBACK capture_dialog_proc(
    HWND dialog, UINT message, WPARAM wparam, LPARAM lparam) {
    CaptureContext *context =
        (CaptureContext *)GetWindowLongPtr(
            dialog, GWLP_USERDATA);
    if (message == WM_INITDIALOG) {
        const char *instruction;
        XInputState state;
        context = (CaptureContext *)lparam;
        SetWindowLongPtr(
            dialog, GWLP_USERDATA, (LONG_PTR)context);
        SetWindowTextA(dialog, "Capture Binding");
        instruction =
            context->device == CAPTURE_KEYBOARD
                ? "Press a supported keyboard key. Press Escape to cancel."
                : context->device == CAPTURE_MOUSE
                    ? "Press a mouse button. Press Escape to cancel."
                    : "Press a controller button or trigger. Press Escape to cancel.";
        add_control(
            dialog, 0, "STATIC", instruction,
            0, 14, 14, 322, 34, 1);
        if (context->device == CAPTURE_MOUSE)
            SetCapture(dialog);
        if (context->device == CAPTURE_GAMEPAD) {
            load_xinput(context);
            if (!find_xinput_controller(context, &state))
                SetDlgItemTextA(
                    dialog, 1,
                    "Connect an XInput controller, then press a button or trigger. "
                    "Press Escape to cancel.");
            SetTimer(dialog, 1, 16, NULL);
        }
        center_dialog(dialog);
        return TRUE;
    }
    if ((message == WM_KEYDOWN || message == WM_SYSKEYDOWN) &&
        context) {
        const char *name;
        if (wparam == VK_ESCAPE) {
            EndDialog(dialog, IDCANCEL);
            return TRUE;
        }
        if (context->device != CAPTURE_KEYBOARD) return TRUE;
        name = key_name_from_message(wparam, lparam);
        if (!name) {
            MessageBeep(MB_ICONWARNING);
            return TRUE;
        }
        capture_complete(dialog, context, name);
        return TRUE;
    }
    if (context && context->device == CAPTURE_MOUSE) {
        const char *name = NULL;
        if (message == WM_LBUTTONDOWN) name = "left";
        else if (message == WM_RBUTTONDOWN) name = "right";
        else if (message == WM_MBUTTONDOWN) name = "middle";
        else if (message == WM_XBUTTONDOWN)
            name = GET_XBUTTON_WPARAM(wparam) == XBUTTON1
                ? "x1" : "x2";
        if (name) {
            ReleaseCapture();
            capture_complete(dialog, context, name);
            return TRUE;
        }
    }
    if (message == WM_TIMER && context &&
        context->device == CAPTURE_GAMEPAD) {
        XInputState state;
        WORD available;
        const char *name;
        if (!context->controller_found) {
            if (!find_xinput_controller(context, &state)) return TRUE;
            SetDlgItemTextA(
                dialog, 1,
                "Press a controller button or trigger. Press Escape to cancel.");
        } else if (context->xinput_get_state(
                       context->controller_index, &state) != ERROR_SUCCESS) {
            context->controller_found = 0;
            SetDlgItemTextA(
                dialog, 1,
                "Controller disconnected. Reconnect it or press Escape to cancel.");
            return TRUE;
        }
        context->blocked_buttons &= state.gamepad.buttons;
        available =
            state.gamepad.buttons & (WORD)~context->blocked_buttons;
        name = xinput_button_name(available);
        if (name) {
            capture_complete(dialog, context, name);
            return TRUE;
        }
        if (context->blocked_left_trigger &&
            state.gamepad.left_trigger <= 30)
            context->blocked_left_trigger = 0;
        if (context->blocked_right_trigger &&
            state.gamepad.right_trigger <= 30)
            context->blocked_right_trigger = 0;
        if (!context->blocked_left_trigger &&
            state.gamepad.left_trigger > 30) {
            capture_complete(dialog, context, "left_trigger");
            return TRUE;
        }
        if (!context->blocked_right_trigger &&
            state.gamepad.right_trigger > 30) {
            capture_complete(dialog, context, "right_trigger");
            return TRUE;
        }
        return TRUE;
    }
    if (message == WM_CLOSE) {
        if (GetCapture() == dialog) ReleaseCapture();
        EndDialog(dialog, IDCANCEL);
        return TRUE;
    }
    return FALSE;
}

static int capture_binding(int device, char *value, size_t value_size) {
    CaptureContext context;
    EmptyDialogTemplate dialog_template;
    INT_PTR result;
    memset(&context, 0, sizeof(context));
    context.device = device;
    memset(&dialog_template, 0, sizeof(dialog_template));
    dialog_template.dialog.style =
        WS_POPUP | WS_CAPTION | WS_SYSMENU |
        DS_MODALFRAME | DS_CENTER;
    dialog_template.dialog.cx = 232;
    dialog_template.dialog.cy = 52;
    result = DialogBoxIndirectParamW(
        GetModuleHandleW(NULL),
        &dialog_template.dialog,
        NULL,
        capture_dialog_proc,
        (LPARAM)&context);
    if (context.xinput_module)
        FreeLibrary(context.xinput_module);
    if (result != IDOK || !context.value[0]) return 0;
    snprintf(value, value_size, "%s", context.value);
    return 1;
}

static int response_text(
    HWND dialog, int identifier, char *text, size_t text_size) {
    return GetDlgItemTextA(
               dialog, identifier, text, (int)text_size) > 0;
}

static int save_settings(
    HWND dialog, InputDialogContext *context) {
    SrInputConfig parsed = context->config;
    char settings[16384];
    char analog_deadzone[32];
    char analog_curve[32];
    char movement_deadzone[32];
    char movement_curve[32];
    char aim_deadzone[32];
    char aim_curve[32];
    char error[512];
    size_t used = 0;
    int index;

    store_current_page(dialog, context);
    settings[0] = 0;
    for (index = 0; index < SR_INPUT_ACTIONS; ++index) {
        if (!append_text(
                settings, sizeof(settings), &used,
                "keyboard.%s = %s\n",
                s_action_names[index],
                context->keyboard[index])) {
            goto too_large;
        }
    }
    for (index = 0; index < SR_INPUT_ANALOG_DIRECTIONS; ++index) {
        if (!append_text(
                settings, sizeof(settings), &used,
                "keyboard.%s = %s\n",
                s_analog_names[index],
                context->keyboard[SR_INPUT_ACTIONS + index])) {
            goto too_large;
        }
    }
    for (index = 0; index < SR_INPUT_ACTIONS; ++index) {
        if (!append_text(
                settings, sizeof(settings), &used,
                "mouse.%s = %s\n",
                s_action_names[index], context->mouse[index]) ||
            !append_text(
                settings, sizeof(settings), &used,
                "gamepad.%s = %s\n",
                s_action_names[index], context->gamepad[index])) {
            goto too_large;
        }
    }
    if (!response_text(
            dialog, IDC_ANALOG_DEADZONE,
            analog_deadzone, sizeof(analog_deadzone)) ||
        !response_text(
            dialog, IDC_ANALOG_CURVE,
            analog_curve, sizeof(analog_curve)) ||
        !response_text(
            dialog, IDC_MOVEMENT_DEADZONE,
            movement_deadzone, sizeof(movement_deadzone)) ||
        !response_text(
            dialog, IDC_MOVEMENT_CURVE,
            movement_curve, sizeof(movement_curve)) ||
        !response_text(
            dialog, IDC_AIM_DEADZONE,
            aim_deadzone, sizeof(aim_deadzone)) ||
        !response_text(
            dialog, IDC_AIM_CURVE,
            aim_curve, sizeof(aim_curve))) {
        MessageBoxA(
            dialog,
            "All deadzone and response curve fields require a value.",
            "Invalid Input Settings", MB_OK | MB_ICONERROR);
        return 0;
    }
    if (!append_text(
            settings, sizeof(settings), &used,
            "analog.deadzone = %s\n"
            "analog.curve = %s\n"
            "analog.invert_y = %s\n"
            "twin_stick.enabled = %s\n"
            "movement.deadzone = %s\n"
            "movement.curve = %s\n"
            "movement.invert_y = %s\n"
            "aim.deadzone = %s\n"
            "aim.curve = %s\n"
            "aim.invert_x = %s\n"
            "aim.invert_y = %s\n",
            analog_deadzone,
            analog_curve,
            IsDlgButtonChecked(dialog, IDC_ANALOG_INVERT_Y) ==
                    BST_CHECKED
                ? "true" : "false",
            IsDlgButtonChecked(dialog, IDC_TWIN_STICK) ==
                    BST_CHECKED
                ? "true" : "false",
            movement_deadzone,
            movement_curve,
            IsDlgButtonChecked(dialog, IDC_MOVEMENT_INVERT_Y) ==
                    BST_CHECKED
                ? "true" : "false",
            aim_deadzone,
            aim_curve,
            IsDlgButtonChecked(dialog, IDC_AIM_INVERT_X) ==
                    BST_CHECKED
                ? "true" : "false",
            IsDlgButtonChecked(dialog, IDC_AIM_INVERT_Y) ==
                    BST_CHECKED
                ? "true" : "false")) {
        goto too_large;
    }
    if (!sr_input_config_parse(
            &parsed, settings, error, sizeof(error))) {
        MessageBoxA(
            dialog, error, "Invalid Input Settings",
            MB_OK | MB_ICONERROR);
        return 0;
    }
    if (!sr_input_config_save(
            &parsed, error, sizeof(error))) {
        MessageBoxA(
            dialog, error, "Cannot Save Input Settings",
            MB_OK | MB_ICONERROR);
        return 0;
    }
    context->config = parsed;
    SetDlgItemTextA(
        dialog, IDC_SAVE_STATUS,
        "Saved. The running game is using these controls now.");
    return 1;

too_large:
    MessageBoxA(
        dialog, "The input settings are too large.",
        "Cannot Save Input Settings", MB_OK | MB_ICONERROR);
    return 0;
}

static void create_response_controls(HWND dialog) {
    static const struct {
        const char *label;
        int identifier;
        int checkbox;
    } controls[] = {
        {"Analog deadzone (0.0-0.95):", IDC_ANALOG_DEADZONE, 0},
        {"Analog response curve (0.1-4.0):", IDC_ANALOG_CURVE, 0},
        {"Invert analog Y", IDC_ANALOG_INVERT_Y, 1},
        {"Enable twin-stick controls", IDC_TWIN_STICK, 1},
        {"Movement deadzone (0.0-0.95):", IDC_MOVEMENT_DEADZONE, 0},
        {"Movement response curve (0.1-4.0):", IDC_MOVEMENT_CURVE, 0},
        {"Invert movement Y", IDC_MOVEMENT_INVERT_Y, 1},
        {"Aim deadzone (0.0-0.95):", IDC_AIM_DEADZONE, 0},
        {"Aim response curve (0.1-4.0):", IDC_AIM_CURVE, 0},
        {"Invert aim X", IDC_AIM_INVERT_X, 1},
        {"Invert aim Y", IDC_AIM_INVERT_Y, 1},
    };
    size_t index;
    for (index = 0; index < sizeof(controls) / sizeof(controls[0]); ++index) {
        int y = 72 + (int)index * 34;
        add_control(
            dialog, 0, "STATIC", controls[index].label,
            0, 24, y + 4, 245, 20,
            IDC_RESPONSE_LABEL_BASE + (int)index);
        if (controls[index].checkbox) {
            add_control(
                dialog, 0, "BUTTON", "",
                WS_TABSTOP | BS_AUTOCHECKBOX,
                286, y, 24, 24, controls[index].identifier);
        } else {
            add_control(
                dialog, WS_EX_CLIENTEDGE, "EDIT", "",
                WS_TABSTOP | ES_AUTOHSCROLL,
                286, y, 140, 24, controls[index].identifier);
        }
    }
}

static INT_PTR CALLBACK input_dialog_proc(
    HWND dialog, UINT message, WPARAM wparam, LPARAM lparam) {
    InputDialogContext *context =
        (InputDialogContext *)GetWindowLongPtr(
            dialog, GWLP_USERDATA);
    if (message == WM_INITDIALOG) {
        HWND device;
        int row;
        context = (InputDialogContext *)lparam;
        SetWindowLongPtr(
            dialog, GWLP_USERDATA, (LONG_PTR)context);
        SetWindowTextA(
            dialog,
            context->title && context->title[0]
                ? context->title : "Input Settings");
        load_binding_texts(context);

        add_control(
            dialog, 0, "STATIC", "Configure:", 0,
            16, 18, 74, 20, 0);
        device = add_control(
            dialog, WS_EX_CLIENTEDGE, "COMBOBOX", "",
            WS_TABSTOP | CBS_DROPDOWNLIST,
            92, 14, 230, 120, IDC_DEVICE);
        SendMessageA(
            device, CB_ADDSTRING, 0, (LPARAM)"Keyboard bindings");
        SendMessageA(
            device, CB_ADDSTRING, 0, (LPARAM)"Mouse bindings");
        SendMessageA(
            device, CB_ADDSTRING, 0, (LPARAM)"Controller bindings");
        SendMessageA(
            device, CB_ADDSTRING, 0, (LPARAM)"Stick response and inversion");
        SendMessage(device, CB_SETCURSEL, INPUT_PAGE_KEYBOARD, 0);
        add_control(
            dialog, 0, "STATIC",
            "Captured input replaces the row. Edit the text to combine up to four "
            "bindings with commas; use none to clear.",
            0, 336, 11, 280, 38, 0);

        for (row = 0; row < INPUT_ROWS; ++row) {
            int y = 54 + row * 27;
            add_control(
                dialog, 0, "STATIC", "",
                0, 16, y + 4, 122, 20,
                IDC_RESPONSE_LABEL_BASE + 32 + row);
            add_control(
                dialog, WS_EX_CLIENTEDGE, "EDIT", "",
                WS_TABSTOP | ES_AUTOHSCROLL,
                140, y, 350, 23,
                IDC_BINDING_EDIT_BASE + row);
            add_control(
                dialog, 0, "BUTTON", "Capture",
                WS_TABSTOP | BS_PUSHBUTTON,
                500, y, 80, 23, IDC_CAPTURE_BASE + row);
        }
        create_response_controls(dialog);
        add_control(
            dialog, 0, "STATIC", "",
            0, 16, 493, 300, 24, IDC_SAVE_STATUS);
        add_control(
            dialog, 0, "BUTTON", "Reset Defaults",
            WS_TABSTOP | BS_PUSHBUTTON,
            16, 520, 108, 29, IDC_RESET_DEFAULTS);
        add_control(
            dialog, 0, "BUTTON", "Save",
            WS_TABSTOP | BS_DEFPUSHBUTTON,
            330, 520, 80, 29, IDOK);
        if (context->allow_launch) {
            add_control(
                dialog, 0, "BUTTON", "Play Game",
                WS_TABSTOP | BS_PUSHBUTTON,
                416, 520, 80, 29, IDC_LAUNCH_GAME);
        }
        add_control(
            dialog, 0, "BUTTON", "Close",
            WS_TABSTOP | BS_PUSHBUTTON,
            502, 520, 80, 29, IDCANCEL);
        load_response_controls(dialog, &context->config);
        show_page(
            dialog, context, INPUT_PAGE_KEYBOARD);
        center_dialog(dialog);
        return TRUE;
    }
    if (message == WM_COMMAND && context) {
        int command = LOWORD(wparam);
        if (command == IDC_DEVICE &&
            HIWORD(wparam) == CBN_SELCHANGE) {
            int page;
            store_current_page(dialog, context);
            page = (int)SendDlgItemMessage(
                dialog, IDC_DEVICE, CB_GETCURSEL, 0, 0);
            if (page >= INPUT_PAGE_KEYBOARD &&
                page <= INPUT_PAGE_RESPONSE) {
                show_page(dialog, context, page);
            }
            return TRUE;
        }
        if (command >= IDC_CAPTURE_BASE &&
            command < IDC_CAPTURE_BASE + INPUT_ROWS) {
            int row = command - IDC_CAPTURE_BASE;
            int device =
                context->page == INPUT_PAGE_KEYBOARD
                    ? CAPTURE_KEYBOARD
                    : context->page == INPUT_PAGE_MOUSE
                        ? CAPTURE_MOUSE : CAPTURE_GAMEPAD;
            char value[32];
            if (row < page_row_count(context->page) &&
                capture_binding(device, value, sizeof(value))) {
                SetDlgItemTextA(
                    dialog, IDC_BINDING_EDIT_BASE + row, value);
                SetDlgItemTextA(dialog, IDC_SAVE_STATUS, "");
            }
            return TRUE;
        }
        if (command == IDC_RESET_DEFAULTS) {
            sr_input_config_defaults(&context->config);
            load_binding_texts(context);
            load_response_controls(dialog, &context->config);
            show_page(dialog, context, context->page);
            SetDlgItemTextA(
                dialog, IDC_SAVE_STATUS,
                "Defaults loaded. Select Save to apply them.");
            return TRUE;
        }
        if (command == IDOK) {
            save_settings(dialog, context);
            return TRUE;
        }
        if (command == IDC_LAUNCH_GAME && context->allow_launch) {
            if (save_settings(dialog, context))
                EndDialog(dialog, IDC_LAUNCH_GAME);
            return TRUE;
        }
        if (command == IDCANCEL) {
            EndDialog(dialog, IDCANCEL);
            return TRUE;
        }
    }
    if (message == WM_CLOSE) {
        EndDialog(dialog, IDCANCEL);
        return TRUE;
    }
    return FALSE;
}

int sr_input_settings_show(const char *title, int allow_launch) {
    const SrInputConfig *current = sr_input_config_get();
    InputDialogContext context;
    EmptyDialogTemplate dialog_template;
    INT_PTR result;

    if (!current) {
        fprintf(
            stderr,
            "input: settings dialog requires initialized config\n");
        return SR_INPUT_SETTINGS_ERROR;
    }
    memset(&context, 0, sizeof(context));
    context.config = *current;
    context.title = title;
    context.allow_launch = allow_launch;
    context.page = INPUT_PAGE_KEYBOARD;
    memset(&dialog_template, 0, sizeof(dialog_template));
    dialog_template.dialog.style =
        WS_POPUP | WS_CAPTION | WS_SYSMENU |
        DS_MODALFRAME | DS_CENTER;
    dialog_template.dialog.cx = 420;
    dialog_template.dialog.cy = 382;
    result = DialogBoxIndirectParamW(
        GetModuleHandleW(NULL),
        &dialog_template.dialog,
        NULL,
        input_dialog_proc,
        (LPARAM)&context);
    if (result == -1) {
        fprintf(
            stderr,
            "input: cannot open settings dialog (error %lu)\n",
            (unsigned long)GetLastError());
        return SR_INPUT_SETTINGS_ERROR;
    }
    if (result == IDC_LAUNCH_GAME) return SR_INPUT_SETTINGS_LAUNCH;
    return result == IDOK
        ? SR_INPUT_SETTINGS_SAVED
        : SR_INPUT_SETTINGS_CLOSED;
}

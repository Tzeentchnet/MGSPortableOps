#include "mgspo_log.h"

#define sr_module_load_image sr_mgspo_module_load_image_builtin
#define sr_module_start sr_mgspo_module_start_builtin
#define sr_module_unload sr_mgspo_module_unload_builtin
#include "../external/psp-recomp/src/rt/module.c"
#undef sr_module_unload
#undef sr_module_start
#undef sr_module_load_image

int iso_init(void);
int iso_lookup(
    const char *guest_path, uint32_t *out_lba, uint32_t *out_size);
int iso_read(
    uint32_t lba, uint32_t offset, void *destination, uint32_t bytes);

typedef struct MgspoModuleLabel {
    uint32_t uid;
    uint32_t base;
    uint32_t size;
    int active;
    char label[256];
} MgspoModuleLabel;

static MgspoModuleLabel *s_module_labels;
static size_t s_module_label_count;
static size_t s_module_label_capacity;

int mgspo_module_identity_active(const char *identity) {
    if (!identity || !identity[0]) return 0;
    for (size_t index = 0; index < s_module_label_count; ++index) {
        const MgspoModuleLabel *label = &s_module_labels[index];
        if (label->active && strcmp(label->label, identity) == 0)
            return 1;
    }
    return 0;
}

uint32_t mgspo_module_uid_active(const char *identity) {
    if (!identity || !identity[0]) return 0;
    for (size_t index = s_module_label_count; index > 0; --index) {
        const MgspoModuleLabel *label =
            &s_module_labels[index - 1];
        if (label->active && strcmp(label->label, identity) == 0)
            return label->uid;
    }
    return 0;
}

static void mgspo_module_label_add(const SrModule *module) {
    if (!module || !module->base || !module->size) return;
    if (s_module_label_count == s_module_label_capacity) {
        size_t capacity =
            s_module_label_capacity
            ? s_module_label_capacity * 2
            : 32;
        MgspoModuleLabel *labels = (MgspoModuleLabel *)realloc(
            s_module_labels, capacity * sizeof(*labels));
        if (!labels) {
            fprintf(
                stderr,
                "module loader: cannot grow interpreter identity table\n");
            abort();
        }
        s_module_labels = labels;
        s_module_label_capacity = capacity;
    }
    MgspoModuleLabel *label =
        &s_module_labels[s_module_label_count++];
    label->uid = module->uid;
    label->base = module->base;
    label->size = module->size;
    label->active = 1;
    snprintf(
        label->label,
        sizeof(label->label),
        "%s",
        strncmp(
            module->path,
            "disc0:/sce_lbn",
            sizeof("disc0:/sce_lbn") - 1) == 0
        ? module->path
        : module->name);
}

static void mgspo_module_label_remove(uint32_t uid) {
    for (size_t index = s_module_label_count; index > 0; --index) {
        MgspoModuleLabel *label = &s_module_labels[index - 1];
        if (label->active && label->uid == uid) {
            label->active = 0;
            return;
        }
    }
}

const char *mgspo_module_name_for_address(uint32_t address) {
    for (size_t index = s_module_label_count; index > 0; --index) {
        const MgspoModuleLabel *label =
            &s_module_labels[index - 1];
        if (label->active &&
            address >= label->base &&
            address - label->base < label->size) {
            return label->label;
        }
    }
    return NULL;
}

uint32_t sr_module_load_image(
    const uint8_t *data, uint32_t size, const char *path) {
    uint32_t uid = sr_mgspo_module_load_image_builtin(data, size, path);
    if ((int32_t)uid < 0) {
        mgspo_log_module(
            path, 0, 0, size, 0, 0, 0, 0, 0, 0, 0, uid);
        return uid;
    }

    SrModule *module = module_by_uid(uid);
    if (module && module->entry == module->base - 1)
        module->entry = UINT32_MAX;
    mgspo_module_label_add(module);
    mgspo_log_module(
        path,
        uid,
        module ? module->base : 0,
        module ? module->size : size,
        module ? module->entry : 0,
        module ? module->gp : 0,
        module ? module->module_start : 0,
        module ? module->module_stop : 0,
        module
            ? (module->start_priority
                ? module->start_priority
                : UINT32_C(0x20))
            : 0,
        module
            ? (module->start_stack_size
                ? module->start_stack_size
                : UINT32_C(0x40000))
            : 0,
        module ? module->start_attr : 0,
        uid);
    return uid;
}

uint32_t sr_module_start(
    uint32_t uid, uint32_t argument_size, uint32_t argument_address,
    uint32_t status_address, uint32_t option_address) {
    SrModule *module = module_by_uid(uid);
    char path[sizeof(module->path)];
    uint32_t entry = 0;
    uint32_t gp = 0;
    if (module) {
        snprintf(path, sizeof(path), "%s", module->path);
        entry = module->entry;
        gp = module->gp;
    } else {
        path[0] = 0;
    }
    mgspo_log_module_callback(
        "start_requested",
        path,
        uid,
        entry,
        gp,
        argument_size,
        argument_address,
        status_address,
        option_address,
        0,
        0);
    uint32_t result = sr_mgspo_module_start_builtin(
        uid,
        argument_size,
        argument_address,
        status_address,
        option_address);
    uint32_t status =
        status_address && guest_range(status_address, 4)
        ? MEM_R32(status_address)
        : 0;
    mgspo_log_module_callback(
        (int32_t)result < 0 ? "start_failed" : "started",
        path,
        uid,
        entry,
        gp,
        argument_size,
        argument_address,
        status_address,
        option_address,
        status,
        result);
    return result;
}

uint32_t sr_module_stop(
    uint32_t uid, uint32_t argument_size, uint32_t argument_address,
    uint32_t status_address, uint32_t option_address) {
    SrModule *module = module_by_uid(uid);
    char path[sizeof(module->path)];
    uint32_t entry = 0;
    uint32_t gp = 0;
    if (module) {
        snprintf(path, sizeof(path), "%s", module->path);
        entry = module->module_stop;
        gp = module->gp;
    } else {
        path[0] = 0;
    }
    mgspo_log_module_callback(
        "stop_requested",
        path,
        uid,
        entry,
        gp,
        argument_size,
        argument_address,
        status_address,
        option_address,
        0,
        0);

    uint32_t result = 0;
    uint32_t status = 0;
    if (!module) {
        result = SCE_KERNEL_ERROR_UNKNOWN_MODULE;
    } else if (!module->started) {
        result = UINT32_C(0x80020135);
    } else if (module->fake || module->hle_replaced) {
        if (status_address && guest_range(status_address, 4))
            MEM_W32(status_address, 0);
        module->started = 0;
    } else if (!entry || entry == UINT32_MAX ||
               !guest_range(entry, 4)) {
        module->started = 0;
    } else {
        uint32_t priority = UINT32_C(0x20);
        uint32_t stack_size = UINT32_C(0x40000);
        uint32_t attributes = 0;
        if (option_address && guest_range(option_address, 20) &&
            MEM_R32(option_address) != 0) {
            uint32_t option_stack = MEM_R32(option_address + 8);
            uint32_t option_priority = MEM_R32(option_address + 12);
            uint32_t option_attributes =
                MEM_R32(option_address + 16);
            if (option_stack) stack_size = option_stack;
            if (option_priority) priority = option_priority;
            if (option_attributes) attributes = option_attributes;
        }

        uint32_t thread = sched_create_thread(
            module->name,
            entry,
            (int)priority,
            stack_size,
            attributes);
        if ((int32_t)thread < 0) {
            result = thread;
        } else {
            sched_set_thread_gp(thread, module->gp);
            result = sched_start_thread(
                thread, argument_size, argument_address);
            if ((int32_t)result < 0) {
                sched_delete_thread(thread);
            } else {
                while (!sched_is_dormant(thread))
                    sched_block_on(thread);
                status = (uint32_t)sched_thread_exit_status(thread);
                if (status_address && guest_range(status_address, 4))
                    MEM_W32(status_address, status);
                sched_delete_thread(thread);
                module->started = 0;
                result = 0;
            }
        }
    }

    mgspo_log_module_callback(
        (int32_t)result < 0 ? "stop_failed" : "stopped",
        path,
        uid,
        entry,
        gp,
        argument_size,
        argument_address,
        status_address,
        option_address,
        status,
        result);
    return result;
}

uint32_t sr_module_unload(uint32_t uid) {
    SrModule *module = module_by_uid(uid);
    char path[sizeof(module->path)];
    uint32_t base = 0;
    uint32_t size = 0;
    if (module) {
        snprintf(path, sizeof(path), "%s", module->path);
        base = module->base;
        size = module->size;
    } else {
        path[0] = 0;
    }
    uint32_t result = sr_mgspo_module_unload_builtin(uid);
    if (result == uid) mgspo_module_label_remove(uid);
    mgspo_log_module_unload(path, uid, base, size, result);
    return result;
}

typedef struct MgspoModuleContract {
    const char *path;
    const char *name;
    const char *sha1;
    const char *export_library;
    uint32_t export_nid;
    uint32_t file_size;
    uint32_t size;
    uint32_t entry_offset;
    uint32_t gp_offset;
} MgspoModuleContract;

static const MgspoModuleContract s_plaintext_contract[] = {
    {
        "disc0:/PSP_GAME/USRDIR/modules/zlibdec.prx",
        "ZLIB",
        "518c64f39a7492340cdcc3411044d555a4faae8d",
        "zlibdec",
        UINT32_C(0x461c7724),
        UINT32_C(19884),
        UINT32_C(0x00004100),
        UINT32_C(0x000016b4),
        UINT32_C(0x0000c090),
    },
    {
        "disc0:/PSP_GAME/USRDIR/modules/sound2.prx",
        "KCEJ_SOUND2",
        "2bb43c7effe0e2454f13dfe3ba90abbce9a83dfd",
        "sound2",
        UINT32_C(0xc9cae432),
        UINT32_C(134912),
        UINT32_C(0x00051400),
        UINT32_MAX,
        UINT32_C(0x00021080),
    },
    {
        "disc0:/PSP_GAME/USRDIR/modules/kjfs.prx",
        "KCEJ_FS",
        "ed7376c5e42652f6554f664621e257a5c9ad26c6",
        "kjfs",
        UINT32_C(0x93e9297f),
        UINT32_C(77744),
        UINT32_C(0x00011a00),
        UINT32_C(0x000025e8),
        UINT32_C(0x000164e0),
    },
};

static uint32_t mgspo_module_contract_load(
    const MgspoModuleContract *contract) {
    uint32_t lba;
    uint32_t size;
    if (iso_lookup(contract->path, &lba, &size) != 0 ||
        size != contract->file_size) {
        fprintf(
            stderr,
            "ERROR: plaintext module contract cannot locate %s.\n",
            contract->path);
        return SCE_KERNEL_ERROR_UNSUPPORTED_PRX_TYPE;
    }

    uint8_t *data = (uint8_t *)malloc(size);
    if (!data || iso_read(lba, 0, data, size) != size) {
        fprintf(
            stderr,
            "ERROR: plaintext module contract cannot read %s.\n",
            contract->path);
        free(data);
        return SCE_KERNEL_ERROR_UNSUPPORTED_PRX_TYPE;
    }
    char sha1[41];
    module_sha1(data, size, sha1);
    if (strcmp(sha1, contract->sha1) != 0) {
        fprintf(
            stderr,
            "ERROR: plaintext module contract hash mismatch for %s.\n",
            contract->path);
        free(data);
        return SCE_KERNEL_ERROR_UNSUPPORTED_PRX_TYPE;
    }

    uint32_t uid =
        sr_module_load_image(data, size, contract->path);
    free(data);
    if ((int32_t)uid < 0) return uid;

    SrModule *module = module_by_uid(uid);
    if (!module ||
        strcmp(module->name, contract->name) != 0 ||
        strcmp(module->path, contract->path) != 0 ||
        module->size != contract->size ||
        (contract->entry_offset == UINT32_MAX
            ? module->entry != UINT32_MAX
            : module->entry !=
                module->base + contract->entry_offset) ||
        module->gp != module->base + contract->gp_offset) {
        fprintf(
            stderr,
            "ERROR: plaintext module metadata mismatch for %s.\n",
            contract->path);
        sr_module_unload(uid);
        return SCE_KERNEL_ERROR_UNSUPPORTED_PRX_TYPE;
    }
    const char *profile_label =
        mgspo_module_name_for_address(module->base);
    if (!profile_label ||
        strcmp(profile_label, contract->name) != 0) {
        fprintf(
            stderr,
            "ERROR: interpreter module identity mismatch for %s.\n",
            contract->path);
        sr_module_unload(uid);
        return SCE_KERNEL_ERROR_UNSUPPORTED_PRX_TYPE;
    }
    uint32_t export_address;
    const char *resolved_library;
    if (!sr_module_find_export(
            contract->export_library,
            contract->export_nid,
            &export_address,
            &resolved_library) ||
        export_address < module->base ||
        export_address >= module->base + module->size) {
        fprintf(
            stderr,
            "ERROR: plaintext module export mismatch for %s.\n",
            contract->path);
        sr_module_unload(uid);
        return SCE_KERNEL_ERROR_UNSUPPORTED_PRX_TYPE;
    }
    return uid;
}

int mgspo_module_verify_plaintext_contract(void) {
    uint32_t uids[_countof(s_plaintext_contract)] = {0};
    uint32_t bases[_countof(s_plaintext_contract)] = {0};
    for (int pass = 0; pass < 2; ++pass) {
        size_t loaded = 0;
        for (size_t index = 0;
             index < _countof(s_plaintext_contract);
             ++index) {
            uint32_t uid =
                mgspo_module_contract_load(
                    &s_plaintext_contract[index]);
            if ((int32_t)uid < 0) {
                fprintf(
                    stderr,
                    "ERROR: plaintext module contract load failed "
                    "for %s (0x%08x).\n",
                    s_plaintext_contract[index].path,
                    uid);
                while (loaded)
                    sr_module_unload(uids[--loaded]);
                return 0;
            }
            uids[loaded++] = uid;
            SrModule *module = module_by_uid(uid);
            if (pass == 0) {
                bases[index] = module->base;
            } else if (module->base != bases[index]) {
                fprintf(
                    stderr,
                    "ERROR: plaintext module base was not reused for %s.\n",
                    s_plaintext_contract[index].path);
                while (loaded)
                    sr_module_unload(uids[--loaded]);
                return 0;
            }
        }

        while (loaded) {
            uint32_t uid = uids[--loaded];
            if (sr_module_unload(uid) != uid) {
                fprintf(
                    stderr,
                    "ERROR: plaintext module contract unload failed.\n");
                return 0;
            }
        }
        for (size_t index = 0;
             index < _countof(s_plaintext_contract);
             ++index) {
            uint32_t export_address;
            const char *resolved_library;
            if (sr_module_find_export(
                    s_plaintext_contract[index].export_library,
                    s_plaintext_contract[index].export_nid,
                    &export_address,
                    &resolved_library)) {
                fprintf(
                    stderr,
                    "ERROR: stale export remained after unloading %s.\n",
                    s_plaintext_contract[index].path);
                return 0;
            }
            const char *stale_identity =
                mgspo_module_name_for_address(bases[index]);
            if (stale_identity) {
                fprintf(
                    stderr,
                    "ERROR: stale interpreter identity remained after "
                    "unloading %s (%s).\n",
                    s_plaintext_contract[index].path,
                    stale_identity);
                return 0;
            }
        }
    }
    return 1;
}

int mgspo_module_verify_policy_contract(void) {
    static const char *path =
        "disc0:/PSP_GAME/USRDIR/modules/libfont.prx";
    uint32_t lba;
    uint32_t size;
    if (iso_init() != 0 ||
        iso_lookup(path, &lba, &size) != 0 ||
        size < 52) {
        fprintf(
            stderr,
            "ERROR: module policy contract could not read %s.\n",
            path);
        return 0;
    }

    uint8_t *data = (uint8_t *)malloc(size);
    if (!data) {
        fprintf(
            stderr,
            "ERROR: module policy contract could not allocate %u bytes.\n",
            size);
        return 0;
    }
    if (iso_read(lba, 0, data, size) != size) {
        fprintf(
            stderr,
            "ERROR: module policy contract read of %s was incomplete.\n",
            path);
        free(data);
        return 0;
    }

    uint32_t uid = sr_module_load_image(data, size, path);
    SrModule *module =
        (int32_t)uid < 0 ? NULL : module_by_uid(uid);
    if (!module || !module->fake || !module->hle_replaced ||
        strcmp(module->path, path) != 0) {
        fprintf(
            stderr,
            "ERROR: exact libfont module policy was not selected.\n");
        if ((int32_t)uid >= 0) sr_module_unload(uid);
        free(data);
        return 0;
    }
    if (sr_module_unload(uid) != uid) {
        fprintf(
            stderr,
            "ERROR: module policy contract could not unload libfont.\n");
        free(data);
        return 0;
    }

    data[size - 1] ^= UINT8_C(1);
    uint32_t mismatch = sr_module_load_image(data, size, path);
    data[size - 1] ^= UINT8_C(1);
    uint32_t unknown = sr_module_load_image(
        data, size,
        "disc0:/PSP_GAME/USRDIR/modules/unknown.prx");
    free(data);
    if (mismatch != SCE_KERNEL_ERROR_UNSUPPORTED_PRX_TYPE ||
        unknown != SCE_KERNEL_ERROR_UNSUPPORTED_PRX_TYPE) {
        fprintf(
            stderr,
            "ERROR: encrypted module policy did not fail closed.\n");
        if ((int32_t)mismatch >= 0) sr_module_unload(mismatch);
        if ((int32_t)unknown >= 0) sr_module_unload(unknown);
        return 0;
    }
    return 1;
}

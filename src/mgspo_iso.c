#define _CRT_SECURE_NO_WARNINGS

#include "mgspo_log.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#define iso_init mgspo_iso_builtin_init
#define iso_list mgspo_iso_builtin_list
#define iso_lookup mgspo_iso_builtin_lookup
#define iso_lookup_info mgspo_iso_builtin_lookup_info
#define iso_read mgspo_iso_builtin_read
#include "../external/psp-recomp/src/rt/iso.c"
#undef iso_read
#undef iso_lookup_info
#undef iso_lookup
#undef iso_list
#undef iso_init

#define MGSPO_DISC_MAP_CAPACITY 4096

typedef struct MgspoDiscMap {
    uint32_t lba;
    uint32_t size;
    FILE *file;
    char path[1024];
} MgspoDiscMap;

static MgspoDiscMap s_disc_map[MGSPO_DISC_MAP_CAPACITY];
static uint32_t s_disc_map_count;

static const char *disc_root(void) {
    const char *root = getenv("MGSPO_DISC_ROOT");
    return root && root[0] ? root : NULL;
}

static int is_raw_lbn_path(const char *path) {
    return path && strstr(path, "sce_lbn") != NULL;
}

static int normalize_disc_path(
    const char *guest_path, char *normalized, size_t capacity) {
    if (!guest_path || !capacity) return 0;
    size_t length = 0;
    int component_start = 1;
    for (const char *cursor = guest_path; *cursor; ++cursor) {
        if (component_start && cursor[0] == '.' &&
            (cursor[1] == '/' || cursor[1] == '\\' || cursor[1] == 0)) {
            continue;
        }
        if (length + 1 >= capacity) return 0;
        normalized[length++] = *cursor;
        component_start =
            *cursor == ':' || *cursor == '/' || *cursor == '\\';
    }
    normalized[length] = 0;
    return 1;
}

static int tree_path(
    const char *guest_path, char *host_path, size_t host_path_size) {
    const char *root = disc_root();
    if (!root || !guest_path || !host_path_size) return -1;

    size_t length = strlen(root);
    if (length >= host_path_size) return -1;
    memcpy(host_path, root, length + 1);
    while (length &&
           (host_path[length - 1] == '\\' || host_path[length - 1] == '/'))
        host_path[--length] = 0;

    const char *cursor = strchr(guest_path, ':');
    cursor = cursor ? cursor + 1 : guest_path;
    while (*cursor == '/' || *cursor == '\\') cursor++;
    while (*cursor) {
        const char *end = cursor;
        while (*end && *end != '/' && *end != '\\') end++;
        size_t component_length = (size_t)(end - cursor);
        if (!component_length ||
            (component_length == 1 && cursor[0] == '.') ||
            (component_length == 2 && cursor[0] == '.' && cursor[1] == '.'))
            return -1;
        if (length + 1 + component_length >= host_path_size) return -1;
        host_path[length++] = '\\';
        memcpy(host_path + length, cursor, component_length);
        length += component_length;
        host_path[length] = 0;
        cursor = end;
        while (*cursor == '/' || *cursor == '\\') cursor++;
    }
    return 0;
}

static int map_file(
    uint32_t lba, uint32_t size, const char *host_path) {
    for (uint32_t index = 0; index < s_disc_map_count; ++index) {
        if (s_disc_map[index].lba != lba) continue;
        if (s_disc_map[index].size != size ||
            _stricmp(s_disc_map[index].path, host_path) != 0) {
            mgspo_log_file_failure("map_collision", host_path, 0x80010005u);
            return -1;
        }
        return 0;
    }
    if (s_disc_map_count == MGSPO_DISC_MAP_CAPACITY) {
        mgspo_log_file_failure("map_capacity", host_path, 0x80010018u);
        return -1;
    }
    MgspoDiscMap *mapping = &s_disc_map[s_disc_map_count++];
    mapping->lba = lba;
    mapping->size = size;
    snprintf(mapping->path, sizeof(mapping->path), "%s", host_path);
    mapping->file = fopen(mapping->path, "rb");
    if (!mapping->file) {
        s_disc_map_count--;
        mgspo_log_file_failure(
            "map_open", host_path, UINT32_C(0x80010005));
        return -1;
    }
    return 0;
}

static MgspoDiscMap *find_mapping(uint32_t lba) {
    for (uint32_t index = 0; index < s_disc_map_count; ++index)
        if (s_disc_map[index].lba == lba) return &s_disc_map[index];
    return NULL;
}

int iso_init(void) {
    int result = mgspo_iso_builtin_init();
    const char *root = disc_root();
    if (result == 0 && root) {
        struct _stat64 status;
        if (_stat64(root, &status) != 0 || !(status.st_mode & _S_IFDIR)) {
            fprintf(
                stderr,
                "disc tree: MGSPO_DISC_ROOT is not a directory: %s\n",
                root);
            mgspo_log_file_failure(
                "mount", root, UINT32_C(0x80010002));
            return -1;
        }
    }
    return result;
}

int iso_lookup_info(
    const char *guest_path,
    uint32_t *out_lba,
    uint32_t *out_size,
    int *out_is_dir) {
    char normalized[1024];
    if (!normalize_disc_path(guest_path, normalized, sizeof(normalized))) {
        mgspo_log_file_failure(
            "normalize", guest_path ? guest_path : "(null)", UINT32_C(0x80010016));
        return -1;
    }
    int result = mgspo_iso_builtin_lookup_info(
        normalized, out_lba, out_size, out_is_dir);
    if (result != 0 || !disc_root() || is_raw_lbn_path(guest_path))
        return result;

    char path[1024];
    struct _stat64 status;
    if (tree_path(normalized, path, sizeof(path)) != 0 ||
        _stat64(path, &status) != 0) {
        mgspo_log_file_failure(
            "lookup", guest_path, UINT32_C(0x80010002));
        return -1;
    }
    int host_is_dir = (status.st_mode & _S_IFDIR) != 0;
    int iso_is_dir = out_is_dir && *out_is_dir;
    if (host_is_dir != iso_is_dir ||
        (!host_is_dir && (uint64_t)status.st_size != *out_size)) {
        mgspo_log_file_failure(
            "identity", guest_path, UINT32_C(0x80010005));
        return -1;
    }
    if (!host_is_dir && map_file(*out_lba, *out_size, path) != 0)
        return -1;
    return 0;
}

int iso_lookup(
    const char *guest_path, uint32_t *out_lba, uint32_t *out_size) {
    int is_dir = 0;
    return iso_lookup_info(guest_path, out_lba, out_size, &is_dir);
}

int iso_list(
    const char *guest_path,
    IsoDirEntry *entries,
    int capacity,
    int *out_count) {
    char normalized[1024];
    if (!normalize_disc_path(guest_path, normalized, sizeof(normalized))) {
        mgspo_log_file_failure(
            "normalize", guest_path ? guest_path : "(null)", UINT32_C(0x80010016));
        return -1;
    }
    if (disc_root()) {
        char path[1024];
        struct _stat64 status;
        if (tree_path(normalized, path, sizeof(path)) != 0 ||
            _stat64(path, &status) != 0 ||
            !(status.st_mode & _S_IFDIR)) {
            mgspo_log_file_failure(
                "list", guest_path, UINT32_C(0x80010002));
            return -1;
        }
    }
    return mgspo_iso_builtin_list(normalized, entries, capacity, out_count);
}

int iso_read(
    uint32_t lba, uint32_t offset, void *destination, uint32_t bytes) {
    MgspoDiscMap *mapping = find_mapping(lba);
    if (!mapping) return mgspo_iso_builtin_read(lba, offset, destination, bytes);
    if (offset > mapping->size) return 0;
    uint32_t available = mapping->size - offset;
    if (bytes > available) bytes = available;
    if (_fseeki64(mapping->file, offset, SEEK_SET) != 0) {
        mgspo_log_file_failure(
            "read_seek", mapping->path, UINT32_C(0x80010005));
        return -1;
    }
    int result = (int)fread(destination, 1, bytes, mapping->file);
    if (result != (int)bytes && ferror(mapping->file))
        mgspo_log_file_failure(
            "read", mapping->path, UINT32_C(0x80010005));
    return result;
}

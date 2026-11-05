#!/usr/bin/env python3
"""Capture and compare bounded KJFS calls against the PPSSPP service oracle."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tomllib
import zlib

import oracle
from iso9660 import Iso


CASES = (
    "open_archive_canonical",
    "size_archive",
    "read_archive_request_8",
    "close_archive",
    "open_direct",
    "size_direct",
    "seek_direct_start_0",
    "read_direct_prefix_8",
    "seek_direct_start_10",
    "read_direct_middle_4",
    "seek_direct_end_minus_4",
    "read_direct_past_eof_8",
    "read_direct_at_eof_4",
    "seek_direct_beyond_eof_49",
    "read_direct_beyond_eof_4",
    "seek_direct_current_plus_2",
    "close_direct",
    "size_closed_handle",
    "read_invalid_handle",
    "close_invalid_handle",
    "open_device_case",
    "close_device_case",
    "open_backslashes",
    "close_backslashes",
    "open_component_case",
    "close_component_case",
    "open_dot_components",
    "close_dot_components",
    "open_double_slash",
    "close_double_slash",
    "open_missing",
    "open_mode_0",
    "close_mode_0",
    "open_mode_2",
    "close_mode_2",
    "open_archive_for_null_buffer",
    "read_null_buffer",
    "close_after_null_buffer",
    "open_archive_for_repeat_reads",
    "read_archive_zero",
    "read_archive_64",
    "close_after_repeat_reads",
    "open_direct_for_negative_seek",
    "seek_direct_negative_start",
    "close_after_negative_seek",
    "seek_invalid_handle",
    "open_direct_for_invalid_whence",
    "seek_direct_invalid_whence",
    "open_direct_component_case",
    "close_direct_component_case",
    "open_direct_dot_component",
    "close_direct_dot_component",
    "open_direct_double_slash",
    "close_direct_double_slash",
    "open_canonical_file",
    "size_canonical_file",
    "read_canonical_file_full",
    "close_canonical_file",
)

SCHEMA = 1
REFERENCE_FILES = ("boot_state.json", "events.jsonl", "oracle.log", "service.done")
CANDIDATE_FILES = ("events.jsonl", "runtime.log", "structured.jsonl")
BLOCKED_REFERENCE_FILES = (
    "boot_state.json", "events.jsonl", "oracle.log", "service.blocked",
)
BLOCKED_CANDIDATE_FILES = (
    "events.jsonl", "runtime.log", "structured.jsonl", "service.blocked",
)
MAX_STEPS = 3_000_000
DEFAULT_STOP = 20
DEFAULT_BLOCKED_RETRIES = 8
PRIVATE_ROOT = oracle.DEFAULT_ORACLE_ROOT / "captures"
ARCHIVE_RESOURCE_PATH = "PSP_GAME/USRDIR/stage/init/_zar"
CANONICAL_FILE_PATH = "disc0:/PSP_GAME/USRDIR/stage/init/data.cnf"
CANONICAL_FILE_PAYLOAD = (
    b".nocache\n.cache\n@cache.qar\ncache.dar\nscenerio.gcx\ninit.rlc\n"
)
CANONICAL_FILE_SHA256 = hashlib.sha256(CANONICAL_FILE_PAYLOAD).hexdigest()
OPEN_PATHS = {
    0: 0x0000, 4: 0x0700, 20: 0x0100, 22: 0x0200, 24: 0x0300,
    26: 0x0400, 28: 0x0500, 30: 0x0600, 31: 0x0000, 33: 0x0000,
    35: 0x0000, 38: 0x0000, 42: 0x0700, 46: 0x0700,
    48: 0x0800, 50: 0x0900, 52: 0x0A00,
    54: 0x0000,
}
PATH_FIXTURES = (
    CANONICAL_FILE_PATH,
    "DISC0:/PSP_GAME/USRDIR/stage/init/data.cnf",
    "disc0:\\PSP_GAME\\USRDIR\\stage\\init\\data.cnf",
    "disc0:/psp_game/usrdir/STAGE/INIT/DATA.CNF",
    "disc0:/PSP_GAME/USRDIR/stage/./init/../init/data.cnf",
    "disc0:/PSP_GAME//USRDIR///stage/init/data.cnf",
    "disc0:/PSP_GAME/USRDIR/stage/init/__mgspo_missing__.bin",
    "disc0:/UMD_DATA.BIN",
    "disc0:/umd_data.bin",
    "disc0:/./UMD_DATA.BIN",
    "disc0://UMD_DATA.BIN",
)
READ_COUNTS = {2: 8, 7: 8, 9: 4, 11: 8, 12: 4, 14: 4,
               18: 4, 36: 4, 39: 0, 40: 64}
SEEK_VALUES = {
    6: (0, 0, 0), 8: (10, 0, 0),
    10: (0xFFFFFFFC, 0xFFFFFFFF, 2), 13: (49, 0, 0),
    15: (2, 0, 1), 43: (0xFFFFFFFF, 0xFFFFFFFF, 0),
    45: (0, 0, 0), 47: (0, 0, 3),
}
BLOCKED_SPECS = {
    20: {
        "operation": {
            "name": "sceIoOpen", "nid": 0x109F50BC,
            "pc": 0x08B761B8, "result": 0x80010002,
        },
        "delay": {
            "name": "sceKernelDelayThreadCB", "nid": 0x68DA9E36,
            "pc": 0x08B761DC, "microseconds": 1_000_000, "result": 0,
        },
    },
    28: {
        "operation": {
            "name": "sceIoOpen", "nid": 0x109F50BC,
            "pc": 0x08B761B8, "result": 0x80010002,
        },
        "delay": {
            "name": "sceKernelDelayThreadCB", "nid": 0x68DA9E36,
            "pc": 0x08B761DC, "microseconds": 1_000_000, "result": 0,
        },
    },
    31: {
        "operation": {
            "name": "sceIoRead", "nid": 0x6A638D83,
            "pc": 0x08B77CB0, "result": 0x80020323,
        },
        "delay": {
            "name": "sceKernelDelayThreadCB", "nid": 0x68DA9E36,
            "pc": 0x08B77CC4, "microseconds": 1_000_000, "result": 0,
        },
    },
    43: {
        "operation": {
            "name": "sceIoLseekAsync", "nid": 0x71B19E77,
            "pc": 0x08B763C4, "result": 0,
        },
        "wait": {
            "name": "sceIoWaitAsyncCB", "nid": 0x35DBD746,
            "pc": 0x08B763D4, "result": 0,
            "async_result_low": 0xFFFFFFFF,
            "async_result_high": 0xFFFFFFFF,
        },
        "delay": {
            "name": "sceKernelDelayThreadCB", "nid": 0x68DA9E36,
            "pc": 0x08B76414, "microseconds": 1_000_000, "result": 0,
        },
    },
    45: {
        "operation": {
            "name": "sceIoLseekAsync", "nid": 0x71B19E77,
            "pc": 0x08B763C4, "result": 0x80020323,
        },
        "delay": {
            "name": "sceKernelDelayThreadCB", "nid": 0x68DA9E36,
            "pc": 0x08B76414, "microseconds": 1_000_000, "result": 0,
        },
    },
}


def _uint(value, name):
    return oracle._integer(value, name)


def _case_kind(name):
    return name.split("_", 1)[0]


def _zar_u32(data, offset, label):
    if offset < 0 or offset + 4 > len(data):
        raise oracle.OracleError(f"init _zar {label} is truncated")
    return struct.unpack_from("<I", data, offset)[0]


def _zar_entries(resource):
    if len(resource) < 5:
        raise oracle.OracleError("init _zar resource is truncated")
    expected_size = _zar_u32(resource, 0, "decompressed size")
    if not 0 < expected_size <= 64 * 1024 * 1024:
        raise oracle.OracleError("init _zar decompressed size is invalid")
    decoder = zlib.decompressobj()
    try:
        archive = decoder.decompress(resource[4:], expected_size + 1)
        if decoder.unconsumed_tail or len(archive) > expected_size:
            raise oracle.OracleError("init _zar exceeds its declared size")
        archive += decoder.flush()
    except zlib.error as error:
        raise oracle.OracleError("init _zar has invalid zlib data") from error
    if (
        len(archive) != expected_size
        or not decoder.eof
        or decoder.unused_data
    ):
        raise oracle.OracleError("init _zar decompressed size is inconsistent")

    count = _zar_u32(archive, 0, "entry count")
    if not 0 < count <= 4096:
        raise oracle.OracleError("init _zar entry count is invalid")
    entries = {}
    offset = 4
    for _ in range(count):
        name_end = archive.find(b"\0", offset, min(len(archive), offset + 256))
        if name_end < 0:
            raise oracle.OracleError("init _zar entry name is invalid")
        try:
            name = archive[offset:name_end].decode("ascii")
        except UnicodeDecodeError as error:
            raise oracle.OracleError("init _zar entry name is not ASCII") from error
        if not name or name in entries:
            raise oracle.OracleError("init _zar has an empty or duplicate entry")
        size_offset = (name_end + 4) & ~3
        size = _zar_u32(archive, size_offset, f"{name} size")
        payload_offset = (size_offset + 19) & ~15
        payload_end = payload_offset + size
        if payload_end >= len(archive) or archive[payload_end] != 0:
            raise oracle.OracleError(f"init _zar entry {name} is outside the resource")
        entries[name] = archive[payload_offset:payload_end]
        offset = payload_end + 1
    if offset != len(archive):
        raise oracle.OracleError("init _zar has trailing data")
    return entries


def _archive_entry_identity(iso_path):
    physical_path = CANONICAL_FILE_PATH.removeprefix("disc0:/")
    with Iso(iso_path) as disc:
        try:
            disc.lookup(physical_path)
        except FileNotFoundError:
            pass
        else:
            raise oracle.OracleError(
                "canonical KJFS entry unexpectedly exists as a physical ISO file"
            )
        resource = disc.read(ARCHIVE_RESOURCE_PATH)
    entries = _zar_entries(resource)
    payload = entries.get("data.cnf")
    if payload != CANONICAL_FILE_PAYLOAD:
        raise oracle.OracleError("init _zar data.cnf payload is unexpected")
    return {
        "container_path": ARCHIVE_RESOURCE_PATH,
        "container_size": len(resource),
        "container_sha256": hashlib.sha256(resource).hexdigest(),
        "entry_path": CANONICAL_FILE_PATH,
        "entry_name": "data.cnf",
        "entry_size": len(payload),
        "entry_sha256": hashlib.sha256(payload).hexdigest(),
        "physical_file": False,
    }


def _arguments(event, name, scratch):
    kind = _case_kind(name)
    count = {"open": 4, "size": 1, "read": 3, "seek": 5, "close": 1}[kind]
    values = event.get("args")
    if not isinstance(values, list) or len(values) != count:
        raise oracle.OracleError(f"{name}: expected {count} call arguments")
    values = [_uint(value, f"{name} argument") for value in values]
    pointers = (0, 3) if kind == "open" else (1,) if kind == "read" else ()
    for index in pointers:
        if values[index]:
            offset = values[index] - scratch
            if not 0 <= offset < 0x10000:
                raise oracle.OracleError(f"{name}: argument is outside scratch memory")
            values[index] = ("scratch", offset)
    return values


def _expected_arguments(stage, handle, canonical_file_size):
    kind = _case_kind(CASES[stage])
    if kind == "open":
        mode = 0 if stage == 31 else 2 if stage == 33 else 1
        return [("scratch", OPEN_PATHS[stage]), mode, 0, ("scratch", 0x2000)]
    if kind == "size":
        return [handle]
    if kind == "read":
        actual_handle = 0x7FFFFFFF if stage == 18 else handle
        buffer = 0 if stage == 36 else ("scratch", 0x1000)
        if stage == 56:
            if canonical_file_size is None:
                raise oracle.OracleError(
                    "read_canonical_file_full requires the preceding size result"
                )
            count = canonical_file_size
        else:
            count = READ_COUNTS[stage]
        return [actual_handle, buffer, count]
    if kind == "seek":
        actual_handle = 0x7FFFFFFF if stage == 45 else handle
        low, high, whence = SEEK_VALUES[stage]
        return [actual_handle, 0, low, high, whence]
    return [0x7FFFFFFF if stage == 19 else handle]


def _blocked_range(stage):
    if stage not in BLOCKED_SPECS:
        raise oracle.OracleError(f"KJFS stage {stage} is not a blocked case")
    return (42, 44) if stage == 43 else (stage, stage + 1)


def _expected_blocked_event(stage, retries):
    event = {
        "event": "kjfs_probe_blocked",
        "stage": stage,
        "case": CASES[stage],
        "retry_count": retries,
        "operation": dict(BLOCKED_SPECS[stage]["operation"]),
    }
    if "wait" in BLOCKED_SPECS[stage]:
        event["wait"] = dict(BLOCKED_SPECS[stage]["wait"])
    event["thread_consistent"] = True
    event["delay"] = dict(BLOCKED_SPECS[stage]["delay"])
    return event


def read_blocked(path, stage, retries):
    start, stop = _blocked_range(stage)
    if not 1 <= retries <= 64:
        raise oracle.OracleError("blocked retry count must be between 1 and 64")
    scratch = None
    current = None
    next_stage = start
    handle = 0
    blocked = None
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as error:
                raise oracle.OracleError(
                    f"{path}:{line_number}: invalid JSON"
                ) from error
            if not isinstance(event, dict):
                raise oracle.OracleError(
                    f"{path}:{line_number}: expected an object"
                )
            event_type = event.get("event")
            if event_type == "kjfs_probe_start":
                if scratch is not None or blocked is not None:
                    raise oracle.OracleError(
                        "duplicate or late KJFS blocked probe start"
                    )
                scratch = _uint(event.get("scratch"), "KJFS scratch")
                if scratch > 0xFFFFFFFF - 0x10000:
                    raise oracle.OracleError("KJFS scratch range overflows")
                if (
                    _uint(event.get("start_stage"), "KJFS start stage") != start
                    or _uint(event.get("stop_stage"), "KJFS stop stage") != stop
                ):
                    raise oracle.OracleError(
                        "KJFS blocked probe start range mismatch"
                    )
            elif event_type == "kjfs_probe_case":
                if scratch is None or blocked is not None:
                    raise oracle.OracleError(
                        "KJFS blocked case outside the active probe"
                    )
                event_stage = _uint(event.get("stage"), "KJFS case stage")
                if event_stage != next_stage or event_stage > stage:
                    raise oracle.OracleError(
                        "missing, duplicated, or reordered KJFS blocked case"
                    )
                name = CASES[event_stage]
                if event.get("case") != name:
                    raise oracle.OracleError(
                        f"KJFS case {event_stage} has the wrong name"
                    )
                phase = event.get("phase")
                if phase == "call":
                    if current is not None:
                        raise oracle.OracleError(f"{name}: duplicate call")
                    arguments = _arguments(event, name, scratch)
                    if arguments != _expected_arguments(
                        event_stage, handle, None
                    ):
                        raise oracle.OracleError(
                            f"{name}: unexpected call arguments"
                        )
                    current = {"stage": event_stage}
                    if _case_kind(name) == "open":
                        path_hex = event.get("path_hex")
                        expected_path = PATH_FIXTURES[
                            OPEN_PATHS[event_stage] // 0x100
                        ]
                        if path_hex != expected_path.encode("ascii").hex():
                            raise oracle.OracleError(
                                f"{name}: unexpected path bytes"
                            )
                elif phase == "return":
                    if current is None:
                        raise oracle.OracleError(
                            f"{name}: return without call"
                        )
                    if event_stage == stage:
                        raise oracle.OracleError(
                            f"{name}: blocked export unexpectedly returned"
                        )
                    result = _uint(event.get("result"), f"{name} result")
                    _uint(event.get("result_hi"), f"{name} high result")
                    if event_stage in OPEN_PATHS:
                        handle = result
                    current = None
                    next_stage += 1
                else:
                    raise oracle.OracleError(f"{name}: invalid case phase")
            elif event_type == "kjfs_probe_blocked":
                if (
                    scratch is None
                    or blocked is not None
                    or current is None
                    or next_stage != stage
                ):
                    raise oracle.OracleError(
                        "incomplete or duplicate KJFS blocked completion"
                    )
                expected = _expected_blocked_event(stage, retries)
                if event != expected:
                    raise oracle.OracleError(
                        "KJFS blocked syscall signature mismatch"
                    )
                blocked = expected
            elif event_type == "kjfs_probe_done":
                raise oracle.OracleError(
                    "KJFS blocked probe used a normal completion event"
                )
    if (
        scratch is None
        or blocked is None
        or current is None
        or next_stage != stage
    ):
        raise oracle.OracleError(
            "KJFS blocked probe did not prove the requested retry sequence"
        )
    return blocked


def read_cases(path, start, stop):
    if not 0 <= start < stop <= len(CASES):
        raise oracle.OracleError("invalid KJFS case range")
    scratch = None
    done = False
    records = []
    current = None
    handle = 0
    canonical_file_size = None
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as error:
                raise oracle.OracleError(
                    f"{path}:{line_number}: invalid JSON"
                ) from error
            if not isinstance(event, dict):
                raise oracle.OracleError(f"{path}:{line_number}: expected an object")
            event_type = event.get("event")
            if event_type == "kjfs_probe_start":
                if scratch is not None or done:
                    raise oracle.OracleError("duplicate or late KJFS probe start")
                scratch = _uint(event.get("scratch"), "KJFS scratch")
                if scratch > 0xFFFFFFFF - 0x10000:
                    raise oracle.OracleError("KJFS scratch range overflows")
                event_start = _uint(event.get("start_stage"), "KJFS start stage")
                event_stop = _uint(event.get("stop_stage"), "KJFS stop stage")
                if event_start != start or event_stop != stop:
                    raise oracle.OracleError("KJFS probe start range mismatch")
            elif event_type == "kjfs_probe_case":
                if scratch is None or done:
                    raise oracle.OracleError("KJFS case outside the active probe")
                stage = start + len(records)
                event_stage = _uint(event.get("stage"), "KJFS case stage")
                if stage >= stop or event_stage != stage:
                    raise oracle.OracleError("missing, duplicated, or reordered KJFS case")
                name = CASES[stage]
                if event.get("case") != name:
                    raise oracle.OracleError(f"KJFS case {stage} has the wrong name")
                if event.get("phase") == "call":
                    if current is not None:
                        raise oracle.OracleError(f"{name}: duplicate call")
                    current = {"args": _arguments(event, name, scratch)}
                    if current["args"] != _expected_arguments(
                        stage, handle, canonical_file_size
                    ):
                        raise oracle.OracleError(f"{name}: unexpected call arguments")
                    if _case_kind(name) == "open":
                        path_hex = event.get("path_hex")
                        expected_path = PATH_FIXTURES[OPEN_PATHS[stage] // 0x100]
                        if path_hex != expected_path.encode("ascii").hex():
                            raise oracle.OracleError(f"{name}: unexpected path bytes")
                        current["path_hex"] = path_hex
                    elif "path_hex" in event:
                        raise oracle.OracleError(f"{name}: unexpected path bytes")
                elif event.get("phase") == "return":
                    if current is None:
                        raise oracle.OracleError(f"{name}: return without call")
                    current["result"] = _uint(event.get("result"), f"{name} result")
                    current["result_hi"] = _uint(
                        event.get("result_hi"), f"{name} high result"
                    )
                    buffer = event.get("buffer_hex")
                    if _case_kind(name) == "read" and name != "read_null_buffer":
                        if not isinstance(buffer, str) or not re.fullmatch(
                            r"[0-9a-f]{128}", buffer
                        ):
                            raise oracle.OracleError(f"{name}: missing 64-byte buffer")
                        current["buffer_hex"] = buffer
                        for field in ("guard_before_hex", "guard_after_hex"):
                            guard = event.get(field)
                            if not isinstance(guard, str) or not re.fullmatch(
                                r"[0-9a-f]{32}", guard
                            ):
                                raise oracle.OracleError(f"{name}: missing 16-byte {field}")
                            if guard != "cc" * 16:
                                raise oracle.OracleError(f"{name}: {field} was modified")
                            current[field] = guard
                    elif buffer is not None:
                        raise oracle.OracleError(f"{name}: unexpected buffer")
                    if stage == 55:
                        canonical_file_size = current["result"]
                        if not 1 <= canonical_file_size <= 64:
                            raise oracle.OracleError(
                                "size_canonical_file: result is outside the guarded buffer"
                            )
                    elif stage == 56:
                        if current["result"] != 0xFFFFFFFF:
                            raise oracle.OracleError(
                                "read_canonical_file_full: unexpected completion sentinel"
                            )
                        payload = bytes.fromhex(current["buffer_hex"])
                        if b"\xcc" in payload[:canonical_file_size]:
                            raise oracle.OracleError(
                                "read_canonical_file_full: transfer left sentinel bytes"
                            )
                        if payload[canonical_file_size:] != (
                            b"\xcc" * (64 - canonical_file_size)
                        ):
                            raise oracle.OracleError(
                                "read_canonical_file_full: modified bytes beyond transfer size"
                            )
                    records.append(current)
                    if stage in OPEN_PATHS and stage != 30:
                        handle = current["result"]
                    current = None
                else:
                    raise oracle.OracleError(f"{name}: invalid case phase")
            elif event_type == "kjfs_probe_done":
                if scratch is None or done or current is not None or len(records) != stop - start:
                    raise oracle.OracleError("incomplete or duplicate KJFS probe completion")
                done = True
    if scratch is None or not done or len(records) != stop - start:
        raise oracle.OracleError("KJFS probe did not complete all requested cases")
    return records


def _verify_service_done(path, start, stop):
    done = oracle._mapping(oracle._load_json(path), "service completion")
    expected = {
        "schema": SCHEMA,
        "start_stage": start,
        "stop_stage": stop,
        "case_count": stop - start,
    }
    for key, value in expected.items():
        if _uint(done.get(key), f"service completion.{key}") != value:
            raise oracle.OracleError(f"service completion {key} mismatch")
    oracle._integer(done.get("steps"), "service completion.steps", 1, MAX_STEPS)


def _verify_service_blocked(path, stage, retries):
    done = oracle._mapping(oracle._load_json(path), "blocked service completion")
    expected = {
        "schema": SCHEMA,
        "stage": stage,
        "case": CASES[stage],
        "retry_count": retries,
    }
    if done != expected:
        raise oracle.OracleError("blocked service completion marker mismatch")


def _file_descriptors(output, names):
    descriptors = {}
    for name in names:
        path = output / name
        if not path.is_file():
            raise oracle.OracleError(f"service capture is missing {name}")
        descriptors[name] = {
            "size": path.stat().st_size,
            "sha256": oracle.hash_file(path),
        }
    return descriptors


def _write_manifest(output, identity, names):
    manifest = {
        "schema": SCHEMA,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "identity": identity,
        "files": _file_descriptors(output, names),
    }
    path = output / "manifest.json"
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "capture.complete").write_text(
        oracle.hash_file(path) + "\n", encoding="ascii"
    )


def _digest(value, name, length):
    value = oracle._string(value, name)
    if not re.fullmatch(rf"[0-9a-f]{{{length}}}", value):
        raise oracle.OracleError(f"{name} has an invalid digest")


def _validate_identity(identity):
    probe = identity.get("probe")
    if probe not in ("kjfs-v3", "kjfs-v4", "kjfs-v5-blocked"):
        raise oracle.OracleError("unsupported KJFS probe identity")
    if probe in ("kjfs-v4", "kjfs-v5-blocked"):
        entry = oracle._mapping(
            identity.get("archive_entry"), "service archive entry identity"
        )
        expected = {
            "container_path": ARCHIVE_RESOURCE_PATH,
            "entry_path": CANONICAL_FILE_PATH,
            "entry_name": "data.cnf",
            "entry_size": len(CANONICAL_FILE_PAYLOAD),
            "entry_sha256": CANONICAL_FILE_SHA256,
            "physical_file": False,
        }
        for key, value in expected.items():
            if entry.get(key) != value or type(entry.get(key)) is not type(value):
                raise oracle.OracleError(f"service archive entry {key} mismatch")
        oracle._integer(
            entry.get("container_size"), "service archive container size", 1
        )
        _digest(
            entry.get("container_sha256"),
            "service archive container sha256",
            64,
        )
    if probe == "kjfs-v5-blocked":
        stage = oracle._integer(
            identity.get("blocked_stage"),
            "service blocked stage",
            0,
            len(CASES) - 1,
        )
        retries = oracle._integer(
            identity.get("retry_count"), "service retry count", 1, 64
        )
        start, stop = _blocked_range(stage)
        if (
            identity.get("start_stage") != start
            or identity.get("stop_stage") != stop
            or retries < 1
        ):
            raise oracle.OracleError("service blocked identity range mismatch")
    disc = oracle._mapping(identity.get("disc"), "service disc identity")
    for key in ("id", "version"):
        oracle._string(disc.get(key), f"service disc.{key}")
    oracle._integer(disc.get("size"), "service disc.size", 1, 2**63 - 1)
    _digest(disc.get("sha1"), "service disc.sha1", 40)
    module = oracle._mapping(identity.get("module"), "service module identity")
    if module.get("name") != "KCEJ_FS":
        raise oracle.OracleError("unexpected service module name")
    oracle._string(module.get("path"), "service module.path")
    _digest(module.get("sha1"), "service module.sha1", 40)
    _uint(module.get("base"), "service module.base")
    oracle._integer(module.get("size"), "service module.size", 1)

    producer = identity.get("producer")
    if producer == "ppsspp":
        build = oracle._mapping(identity.get("build"), "service reference build")
        oracle._integer(build.get("schema"), "service reference build.schema", 1, 1)
        oracle._string(build.get("ppsspp_version"), "service reference version")
        _digest(build.get("ppsspp_commit"), "service reference commit", 40)
        _digest(build.get("patch_sha256"), "service reference patch", 64)
        _digest(build.get("executable_sha256"), "service reference executable", 64)
        for key in ("compiler", "vc_tools_version", "visual_studio",
                    "windows_sdk", "cmake", "ninja"):
            oracle._string(build.get(key), f"service reference build.{key}")
        if build.get("configuration") != "Release" or build.get("architecture") != "x64":
            raise oracle.OracleError("unexpected service reference build configuration")
        settings = oracle._mapping(identity.get("settings"), "service reference settings")
        for key, value in oracle.EXPECTED_SETTINGS.items():
            if settings.get(key) != value or type(settings.get(key)) is not type(value):
                raise oracle.OracleError(f"service reference setting {key} mismatch")
        if identity.get("max_steps") != MAX_STEPS:
            raise oracle.OracleError("unexpected service reference instruction limit")
    elif producer == "standalone":
        _digest(identity.get("executable_sha256"), "service candidate executable", 64)
        _digest(identity.get("probe_source_sha256"), "service candidate probe source", 64)
        _digest(identity.get("runtime_source_sha256"), "service candidate runtime source", 64)
        _digest(identity.get("iso_source_sha256"), "service candidate ISO source", 64)
        if identity.get("disc_source") not in ("iso", "extracted"):
            raise oracle.OracleError("unexpected service candidate disc source")
        if not isinstance(identity.get("native_zlib"), bool):
            raise oracle.OracleError("unexpected service candidate ZLIB mode")
    else:
        raise oracle.OracleError("unknown service capture producer")


def verify_capture(output):
    output = output.resolve()
    path = output / "manifest.json"
    manifest = oracle._mapping(oracle._load_json(path), "service manifest")
    oracle._integer(manifest.get("schema"), "service capture schema", SCHEMA, SCHEMA)
    identity = oracle._mapping(manifest.get("identity"), "service identity")
    _validate_identity(identity)
    producer = identity.get("producer")
    blocked = identity.get("probe") == "kjfs-v5-blocked"
    if producer == "ppsspp":
        names = BLOCKED_REFERENCE_FILES if blocked else REFERENCE_FILES
    elif producer == "standalone":
        names = BLOCKED_CANDIDATE_FILES if blocked else CANDIDATE_FILES
    else:
        raise oracle.OracleError("unknown service capture producer")
    completion = output / "capture.complete"
    if not completion.is_file():
        raise oracle.OracleError("service capture completion marker is missing")
    if completion.read_text(encoding="ascii").strip() != oracle.hash_file(path):
        raise oracle.OracleError("service capture completion marker mismatch")
    files = oracle._mapping(manifest.get("files"), "service capture files")
    if set(files) != set(names) or files != _file_descriptors(output, names):
        raise oracle.OracleError("service capture payload does not match its manifest")
    if blocked:
        stage = identity["blocked_stage"]
        retries = identity["retry_count"]
        signature = read_blocked(output / "events.jsonl", stage, retries)
        _verify_service_blocked(
            output / "service.blocked", stage, retries
        )
        return manifest, signature
    start = oracle._integer(
        identity.get("start_stage"), "start_stage", 0, len(CASES) - 1
    )
    stop = oracle._integer(
        identity.get("stop_stage"), "stop_stage", 1, len(CASES)
    )
    cases = read_cases(output / "events.jsonl", start, stop)
    if producer == "ppsspp":
        _verify_service_done(output / "service.done", start, stop)
    return manifest, cases


def compare_captures(reference, candidate, config=None):
    reference_manifest, reference_cases = verify_capture(reference)
    candidate_manifest, candidate_cases = verify_capture(candidate)
    left = reference_manifest["identity"]
    right = candidate_manifest["identity"]
    if left.get("producer") != "ppsspp" or right.get("producer") != "standalone":
        raise oracle.OracleError("expected PPSSPP reference and standalone candidate")
    identity_keys = [
        "disc", "module", "probe", "archive_entry", "start_stage", "stop_stage",
    ]
    if left.get("probe") == "kjfs-v5-blocked":
        identity_keys.extend(("blocked_stage", "retry_count"))
    for key in identity_keys:
        if key not in left or left[key] != right.get(key):
            raise oracle.OracleError(f"service capture identity mismatch: {key}")
    if config is not None:
        if left.get("probe") == "kjfs-v5-blocked":
            expected_identity = _blocked_identity(
                config,
                config.disc["iso_sha1"],
                left["blocked_stage"],
                left["retry_count"],
            )
        else:
            expected_identity = _identity(
                config,
                config.disc["iso_sha1"],
                left["start_stage"],
                left["stop_stage"],
            )
        for key, value in expected_identity.items():
            if left.get(key) != value:
                raise oracle.OracleError(f"service capture is stale: {key}")
        build = left["build"]
        for key, value in {
            "ppsspp_version": config.version,
            "ppsspp_commit": config.commit,
            "patch_sha256": oracle.hash_file(config.patch),
        }.items():
            if build.get(key) != value:
                raise oracle.OracleError(f"service reference is stale: {key}")
        if right["probe_source_sha256"] != oracle.hash_file(
            oracle.ROOT / "src" / "mgspo_kjfs_probe.c"
        ):
            raise oracle.OracleError("service candidate probe source is stale")
        if right["runtime_source_sha256"] != oracle.hash_file(
            oracle.ROOT / "src" / "mgspo_hle.c"
        ):
            raise oracle.OracleError("service candidate runtime source is stale")
        if right["iso_source_sha256"] != oracle.hash_file(
            oracle.ROOT / "src" / "mgspo_iso.c"
        ):
            raise oracle.OracleError("service candidate ISO source is stale")
    if left.get("probe") == "kjfs-v5-blocked":
        if reference_cases != candidate_cases:
            raise oracle.OracleError("KJFS blocked syscall signatures differ")
        print(
            "KJFS blocked service comparison matched "
            f"stage {left['blocked_stage']} for {left['retry_count']} retries"
        )
        return
    start = left["start_stage"]
    for index, (expected, actual) in enumerate(zip(reference_cases, candidate_cases)):
        stage = start + index
        name = CASES[stage]
        fields = ["args", "result"]
        if "path_hex" in expected:
            fields.append("path_hex")
        if _case_kind(name) == "seek":
            fields.append("result_hi")
        if "buffer_hex" in expected:
            fields.extend(("buffer_hex", "guard_before_hex", "guard_after_hex"))
        for field in fields:
            if expected[field] != actual[field]:
                raise oracle.OracleError(
                    f"KJFS case {stage} ({name}) {field} differs: "
                    f"reference={expected[field]!r}, candidate={actual[field]!r}"
                )
    count = len(reference_cases)
    print(f"KJFS service comparison matched {count} {'case' if count == 1 else 'cases'}")


def _identity(config, iso_sha1, start, stop, archive_entry=None):
    with config.config_path.open("rb") as stream:
        settings = tomllib.load(stream)
    module = settings["plaintext_modules"]["kjfs"]
    sha1 = oracle._string(module.get("sha1"), "plaintext_modules.kjfs.sha1")
    if not re.fullmatch(r"[0-9a-f]{40}", sha1):
        raise oracle.OracleError("invalid KJFS module SHA-1")
    identity = {
        "disc": {
            "id": config.disc["id"],
            "version": config.disc["version"],
            "size": config.disc["iso_size"],
            "sha1": iso_sha1,
        },
        "module": {
            "name": "KCEJ_FS",
            "path": module["path"],
            "sha1": sha1,
            "base": module["base"],
            "size": module["size"],
        },
        "probe": "kjfs-v4",
        "start_stage": start,
        "stop_stage": stop,
    }
    if archive_entry is not None:
        identity["archive_entry"] = archive_entry
    return identity


def _blocked_identity(
    config, iso_sha1, stage, retries, archive_entry=None,
):
    start, stop = _blocked_range(stage)
    identity = _identity(
        config, iso_sha1, start, stop, archive_entry
    )
    identity.update({
        "probe": "kjfs-v5-blocked",
        "blocked_stage": stage,
        "retry_count": retries,
    })
    return identity


def _environment():
    return {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith(("SR_", "MGSPO_", "PSPRECOMP_"))
        and key.upper() != "PSP_ISO"
    }


def _new_output(output):
    output = output.resolve()
    try:
        output.relative_to(PRIVATE_ROOT.resolve())
    except ValueError as error:
        raise oracle.OracleError(
            f"service output must be under {PRIVATE_ROOT}"
        ) from error
    if output.exists():
        raise oracle.OracleError(f"service output already exists: {output}")
    output.mkdir(parents=True)
    (output / "memstick").mkdir()
    return output


def _run(command, cwd, environment, log_path, timeout):
    print("> " + subprocess.list2cmdline([str(item) for item in command]))
    with log_path.open("x", encoding="utf-8", newline="") as log:
        try:
            process = subprocess.run(
                [str(item) for item in command],
                cwd=cwd,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise oracle.OracleError(
                f"service capture timed out; see {log_path}"
            ) from error
    if process.returncode:
        raise oracle.OracleError(
            f"service capture exited {process.returncode}; see {log_path}"
        )


def capture_reference(config, checkout, build_dir, iso, output, start, stop, timeout):
    checkout = checkout.resolve()
    build_dir = build_dir.resolve()
    iso = iso.resolve()
    oracle.verify_checkout(config, checkout, require_patch=True)
    executable = build_dir / f"{config.build['target']}.exe"
    build_identity = oracle.verify_build_identity(
        config, build_dir / "mgspo_oracle_build.json", executable
    )
    iso_sha1 = oracle.verify_iso(config, iso)
    identity = _identity(
        config, iso_sha1, start, stop, _archive_entry_identity(iso)
    )
    output = _new_output(output)
    environment = _environment()
    environment.update(
        {
            "PSPRECOMP_ORACLE_DIR": str(output),
            "PSPRECOMP_ORACLE_START_PC": f"{config.module['entry']:08x}",
            "PSPRECOMP_ORACLE_STEPS": str(MAX_STEPS),
            "PSPRECOMP_ORACLE_TARGET": config.module["name"],
            "PSPRECOMP_ORACLE_MEMSTICK": str(output / "memstick"),
            "PSPRECOMP_ORACLE_RTC_EPOCH": str(config.settings["rtc_epoch_seconds"]),
            "PSPRECOMP_ORACLE_KJFS_PROBE": "1",
            "PSPRECOMP_ORACLE_KJFS_PROBE_STAGE": str(start),
            "PSPRECOMP_ORACLE_KJFS_PROBE_STOP": str(stop),
            "PSPRECOMP_ORACLE_EVENTS_ONLY": "1",
        }
    )
    _run(
        [executable, "-i", "--graphics=software", f"--timeout={timeout}", iso],
        checkout, environment, output / "oracle.log", timeout + 30,
    )
    boot_state = oracle._load_json(output / "boot_state.json")
    if boot_state.get("entry_pc") != config.module["entry"]:
        raise oracle.OracleError("service capture entry PC does not match the title")
    _verify_service_done(output / "service.done", start, stop)
    read_cases(output / "events.jsonl", start, stop)
    identity.update(
        {
            "producer": "ppsspp",
            "build": build_identity,
            "settings": config.settings,
            "max_steps": MAX_STEPS,
        }
    )
    _write_manifest(output, identity, REFERENCE_FILES)
    print(f"PPSSPP service capture complete: {output}")


def capture_candidate(
    config, executable, iso, output, start, stop, timeout, native_zlib=True,
    disc_root=None,
):
    executable = executable.resolve()
    iso = iso.resolve()
    if not executable.is_file():
        raise oracle.OracleError(f"standalone executable not found: {executable}")
    if disc_root is not None:
        disc_root = disc_root.resolve()
        if not disc_root.is_dir():
            raise oracle.OracleError(f"extracted disc root not found: {disc_root}")
    iso_sha1 = oracle.verify_iso(config, iso)
    identity = _identity(
        config, iso_sha1, start, stop, _archive_entry_identity(iso)
    )
    output = _new_output(output)
    environment = _environment()
    environment.update(
        {
            "PSP_ISO": str(iso),
            "SR_MEMSTICK": str(output / "memstick"),
            "SR_GPU": "sw",
            "SR_GRAPHICS_CONFIG": "0",
            "SR_NO_DIALOGS": "1",
            "SR_NOVBPACE": "1",
            "MGSPO_ENABLE_NATIVE_ZLIB": "1" if native_zlib else "0",
            "MGSPO_KJFS_PROBE_OUTPUT": str(output / "events.jsonl"),
            "MGSPO_KJFS_PROBE_STAGE": str(start),
            "MGSPO_KJFS_PROBE_STOP": str(stop),
        }
    )
    if disc_root is not None:
        environment["MGSPO_DISC_ROOT"] = str(disc_root)
    _run(
        [executable, "--headless", "--log", output / "structured.jsonl"],
        output, environment, output / "runtime.log", timeout,
    )
    read_cases(output / "events.jsonl", start, stop)
    identity.update(
        {
            "producer": "standalone",
            "executable_sha256": oracle.hash_file(executable),
            "native_zlib": native_zlib,
            "disc_source": "extracted" if disc_root is not None else "iso",
            "probe_source_sha256": oracle.hash_file(
                oracle.ROOT / "src" / "mgspo_kjfs_probe.c"
            ),
            "runtime_source_sha256": oracle.hash_file(
                oracle.ROOT / "src" / "mgspo_hle.c"
            ),
            "iso_source_sha256": oracle.hash_file(
                oracle.ROOT / "src" / "mgspo_iso.c"
            ),
        }
    )
    _write_manifest(output, identity, CANDIDATE_FILES)
    print(f"standalone service capture complete: {output}")


def capture_blocked_reference(
    config, checkout, build_dir, iso, output, stage, retries, timeout,
):
    checkout = checkout.resolve()
    build_dir = build_dir.resolve()
    iso = iso.resolve()
    oracle.verify_checkout(config, checkout, require_patch=True)
    executable = build_dir / f"{config.build['target']}.exe"
    build_identity = oracle.verify_build_identity(
        config, build_dir / "mgspo_oracle_build.json", executable
    )
    iso_sha1 = oracle.verify_iso(config, iso)
    identity = _blocked_identity(
        config, iso_sha1, stage, retries, _archive_entry_identity(iso)
    )
    start, stop = _blocked_range(stage)
    output = _new_output(output)
    environment = _environment()
    environment.update({
        "PSPRECOMP_ORACLE_DIR": str(output),
        "PSPRECOMP_ORACLE_START_PC": f"{config.module['entry']:08x}",
        "PSPRECOMP_ORACLE_STEPS": str(MAX_STEPS),
        "PSPRECOMP_ORACLE_TARGET": config.module["name"],
        "PSPRECOMP_ORACLE_MEMSTICK": str(output / "memstick"),
        "PSPRECOMP_ORACLE_RTC_EPOCH": str(
            config.settings["rtc_epoch_seconds"]
        ),
        "PSPRECOMP_ORACLE_KJFS_PROBE": "1",
        "PSPRECOMP_ORACLE_KJFS_PROBE_STAGE": str(start),
        "PSPRECOMP_ORACLE_KJFS_PROBE_STOP": str(stop),
        "PSPRECOMP_ORACLE_KJFS_BLOCK_STAGE": str(stage),
        "PSPRECOMP_ORACLE_KJFS_BLOCK_RETRIES": str(retries),
        "PSPRECOMP_ORACLE_EVENTS_ONLY": "1",
    })
    _run(
        [executable, "-i", "--graphics=software", f"--timeout={timeout}", iso],
        checkout, environment, output / "oracle.log", timeout + 30,
    )
    boot_state = oracle._load_json(output / "boot_state.json")
    if boot_state.get("entry_pc") != config.module["entry"]:
        raise oracle.OracleError(
            "blocked service capture entry PC does not match the title"
        )
    read_blocked(output / "events.jsonl", stage, retries)
    _verify_service_blocked(output / "service.blocked", stage, retries)
    identity.update({
        "producer": "ppsspp",
        "build": build_identity,
        "settings": config.settings,
        "max_steps": MAX_STEPS,
    })
    _write_manifest(output, identity, BLOCKED_REFERENCE_FILES)
    print(f"PPSSPP blocked service capture complete: {output}")


def capture_blocked_candidate(
    config, executable, iso, output, stage, retries, timeout,
    native_zlib=True, disc_root=None,
):
    executable = executable.resolve()
    iso = iso.resolve()
    if not executable.is_file():
        raise oracle.OracleError(
            f"standalone executable not found: {executable}"
        )
    if disc_root is not None:
        disc_root = disc_root.resolve()
        if not disc_root.is_dir():
            raise oracle.OracleError(
                f"extracted disc root not found: {disc_root}"
            )
    iso_sha1 = oracle.verify_iso(config, iso)
    identity = _blocked_identity(
        config, iso_sha1, stage, retries, _archive_entry_identity(iso)
    )
    start, stop = _blocked_range(stage)
    output = _new_output(output)
    environment = _environment()
    environment.update({
        "PSP_ISO": str(iso),
        "SR_MEMSTICK": str(output / "memstick"),
        "SR_GPU": "sw",
        "SR_GRAPHICS_CONFIG": "0",
        "SR_NO_DIALOGS": "1",
        "SR_NOVBPACE": "1",
        "MGSPO_ENABLE_NATIVE_ZLIB": "1" if native_zlib else "0",
        "MGSPO_KJFS_PROBE_OUTPUT": str(output / "events.jsonl"),
        "MGSPO_KJFS_PROBE_STAGE": str(start),
        "MGSPO_KJFS_PROBE_STOP": str(stop),
        "MGSPO_KJFS_BLOCK_STAGE": str(stage),
        "MGSPO_KJFS_BLOCK_RETRIES": str(retries),
        "MGSPO_KJFS_BLOCKED_OUTPUT": str(
            output / "service.blocked"
        ),
    })
    if disc_root is not None:
        environment["MGSPO_DISC_ROOT"] = str(disc_root)
    _run(
        [executable, "--headless", "--log", output / "structured.jsonl"],
        output, environment, output / "runtime.log", timeout,
    )
    read_blocked(output / "events.jsonl", stage, retries)
    _verify_service_blocked(output / "service.blocked", stage, retries)
    identity.update({
        "producer": "standalone",
        "executable_sha256": oracle.hash_file(executable),
        "native_zlib": native_zlib,
        "disc_source": "extracted" if disc_root is not None else "iso",
        "probe_source_sha256": oracle.hash_file(
            oracle.ROOT / "src" / "mgspo_kjfs_probe.c"
        ),
        "runtime_source_sha256": oracle.hash_file(
            oracle.ROOT / "src" / "mgspo_hle.c"
        ),
        "iso_source_sha256": oracle.hash_file(
            oracle.ROOT / "src" / "mgspo_iso.c"
        ),
    })
    _write_manifest(output, identity, BLOCKED_CANDIDATE_FILES)
    print(f"standalone blocked service capture complete: {output}")


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=oracle.DEFAULT_CONFIG)
    commands = parser.add_subparsers(dest="command", required=True)
    reference = commands.add_parser("capture-reference")
    reference.add_argument("iso", type=Path)
    reference.add_argument("output", type=Path)
    reference.add_argument("--checkout", type=Path, default=oracle.DEFAULT_CHECKOUT)
    reference.add_argument("--build-dir", type=Path, default=oracle.DEFAULT_BUILD)
    candidate = commands.add_parser("capture-candidate")
    candidate.add_argument("executable", type=Path)
    candidate.add_argument("iso", type=Path)
    candidate.add_argument("output", type=Path)
    candidate.add_argument(
        "--interpreted-zlib", dest="native_zlib", action="store_false",
        help="use interpreter fallback instead of generated ZLIB code",
    )
    candidate.add_argument(
        "--disc-root", type=Path,
        help="use this extracted disc tree instead of ISO-backed file reads",
    )
    for command in (reference, candidate):
        command.add_argument("--start", type=int, default=0)
        command.add_argument("--stop", type=int, default=DEFAULT_STOP)
        command.add_argument("--timeout", type=int, default=300)
    blocked_reference = commands.add_parser("capture-blocked-reference")
    blocked_reference.add_argument("iso", type=Path)
    blocked_reference.add_argument("output", type=Path)
    blocked_reference.add_argument(
        "--checkout", type=Path, default=oracle.DEFAULT_CHECKOUT
    )
    blocked_reference.add_argument(
        "--build-dir", type=Path, default=oracle.DEFAULT_BUILD
    )
    blocked_candidate = commands.add_parser("capture-blocked-candidate")
    blocked_candidate.add_argument("executable", type=Path)
    blocked_candidate.add_argument("iso", type=Path)
    blocked_candidate.add_argument("output", type=Path)
    blocked_candidate.add_argument(
        "--interpreted-zlib", dest="native_zlib", action="store_false",
        help="use interpreter fallback instead of generated ZLIB code",
    )
    blocked_candidate.add_argument(
        "--disc-root", type=Path,
        help="use this extracted disc tree instead of ISO-backed file reads",
    )
    for command in (blocked_reference, blocked_candidate):
        command.add_argument(
            "--stage", type=int, required=True, choices=tuple(BLOCKED_SPECS)
        )
        command.add_argument(
            "--retries", type=int, default=DEFAULT_BLOCKED_RETRIES
        )
        command.add_argument("--timeout", type=int, default=300)
    comparison = commands.add_parser("compare")
    comparison.add_argument("reference", type=Path)
    comparison.add_argument("candidate", type=Path)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        if args.command == "compare":
            compare_captures(
                args.reference, args.candidate, oracle.load_config(args.config)
            )
            return 0
        if args.command.startswith("capture-blocked-"):
            if not 1 <= args.retries <= 64:
                raise oracle.OracleError(
                    "blocked retry count must be between 1 and 64"
                )
            if args.timeout < 1:
                raise oracle.OracleError("timeout must be positive")
            config = oracle.load_config(args.config)
            if args.command == "capture-blocked-reference":
                capture_blocked_reference(
                    config, args.checkout, args.build_dir, args.iso,
                    args.output, args.stage, args.retries, args.timeout,
                )
            else:
                capture_blocked_candidate(
                    config, args.executable, args.iso, args.output,
                    args.stage, args.retries, args.timeout,
                    args.native_zlib, args.disc_root,
                )
            return 0
        if not 0 <= args.start < args.stop <= len(CASES):
            raise oracle.OracleError("invalid KJFS case range")
        if args.timeout < 1:
            raise oracle.OracleError("timeout must be positive")
        config = oracle.load_config(args.config)
        if args.command == "capture-reference":
            capture_reference(
                config, args.checkout, args.build_dir, args.iso, args.output,
                args.start, args.stop, args.timeout,
            )
        else:
            capture_candidate(
                config, args.executable, args.iso, args.output,
                args.start, args.stop, args.timeout, args.native_zlib,
                args.disc_root,
            )
        return 0
    except (
        KeyError, OSError, UnicodeError, oracle.OracleError,
        subprocess.SubprocessError, tomllib.TOMLDecodeError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

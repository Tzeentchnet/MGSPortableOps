#!/usr/bin/env python3
"""Run and verify the deterministic clean-save first-mission route."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import tomllib

from ppm import read_ppm, validate_region

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "mgspo.toml"
MISSION_MODULE = "disc0:/sce_lbn0x68110_size0x10c724"
MISSION_BASE = "08b86f00"
MISSION_ACTIVE_MARKER = "first-mission automation: mission active at present="
PAUSE_MARKER = "first-mission pause checkpoint reached at present="
D3D12_COHERENCY_MARKER = (
    "mgspo: D3D12 framebuffer write synchronization enabled"
)
D3D12_HARDWARE_TEXTURE_MARKER = (
    "mgspo: D3D12 hardware texture path enabled"
)
D3D12_PRESENT_BATCH_MARKER = (
    "mgspo: D3D12 batched CPU-present readback"
)


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("iso", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--route", type=Path)
    parser.add_argument("--present", type=int)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--expected-frame-sha256")
    parser.add_argument("--expected-frame-region-sha256")
    parser.add_argument("--keep-structured-log", action="store_true")
    parser.add_argument(
        "--renderer",
        choices=("sw", "d3d12"),
        default="sw",
        help="renderer to verify (d3d12 requires the experimental build)",
    )
    parser.add_argument(
        "--turbo",
        action="store_true",
        help="disable PSP vblank pacing for profiling",
    )
    zlib_mode = parser.add_mutually_exclusive_group()
    zlib_mode.add_argument(
        "--native-zlib",
        dest="native_zlib",
        action="store_true",
        help="use generated ZLIB code (the default)",
    )
    zlib_mode.add_argument(
        "--interpreted-zlib",
        dest="native_zlib",
        action="store_false",
        help="disable generated ZLIB code for comparison",
    )
    parser.set_defaults(native_zlib=True)
    return parser.parse_args(argv[1:])


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_ppm_region(path, region):
    image = read_ppm(path)
    x, y, region_width, region_height = validate_region(
        region, image.width, image.height
    )
    digest = hashlib.sha256()
    row_bytes = image.width * 3
    region_bytes = region_width * 3
    for row in range(y, y + region_height):
        start = row * row_bytes + x * 3
        digest.update(image.pixels[start:start + region_bytes])
    return digest.hexdigest()


def validate_log(content, present, native_zlib=False, renderer="sw"):
    required = [
        MISSION_ACTIVE_MARKER,
        PAUSE_MARKER,
        f"module loader: allocated {MISSION_MODULE} at {MISSION_BASE}-",
        f"gui_init: GE backend {renderer}\n",
    ]
    forbidden = [
        "HLE: unimplemented ",
        "dispatch: interpreter stopped",
        "sceIoOpen: not found: umd",
        " has no HLE policy",
        "module loader: policy rejects ",
        "mgspo fatal",
        f"presentation limit reached at present {present}",
    ]
    if renderer == "d3d12":
        required.extend(
            (
                D3D12_COHERENCY_MARKER,
                D3D12_HARDWARE_TEXTURE_MARKER,
                D3D12_PRESENT_BATCH_MARKER,
            )
        )
        forbidden.extend(
            (
                "ged3d12: CPU write invalidated a newer GPU framebuffer",
                "ged3d12: framebuffer partial readback failed",
                "gui_present: D3D12 backend failed",
                "mgspo: D3D12 CPU-present framebuffer synchronization failed",
                "mgspo: D3D12 CPU-present batching skipped",
            )
        )
    missing = [marker for marker in required if marker not in content]
    failures = [marker for marker in forbidden if marker in content]
    hle_modules = [
        line
        for line in content.splitlines()
        if line.startswith("module loader: HLE-only module ")
    ]
    if len(hle_modules) != 1 or " libfont.prx " not in hle_modules[0]:
        failures.append(
            "encrypted-module inventory changed: "
            + (", ".join(hle_modules) if hle_modules else "(none)")
        )
    zlib_modules = [
        line
        for line in content.splitlines()
        if line.startswith("module loader: ZLIB ")
    ]
    native_active = (
        len(zlib_modules) == 1
        and zlib_modules[0].endswith(" (native)")
    )
    if len(zlib_modules) != 1 or native_active != native_zlib:
        failures.append(
            f"ZLIB mode was not "
            f"{'native' if native_zlib else 'interpreted'}: "
            + (", ".join(zlib_modules) if zlib_modules else "(none)")
        )
    if missing or failures:
        details = []
        if missing:
            details.append("missing markers: " + ", ".join(missing))
        if failures:
            details.append("failure markers: " + ", ".join(failures))
        raise ValueError("; ".join(details))


def read_route_checkpoint(content, marker, label):
    markers = [
        line
        for line in content.splitlines()
        if line.startswith(marker)
    ]
    if len(markers) != 1:
        raise ValueError(
            f"expected one {label} marker, found {len(markers)}"
        )
    payload = markers[0][len(marker):]
    fields = payload.split(" vblank=")
    if len(fields) != 2:
        raise ValueError(f"malformed {label} marker: {markers[0]}")
    try:
        present = int(fields[0])
        vblank = int(fields[1])
    except ValueError as error:
        raise ValueError(
            f"malformed {label} marker: {markers[0]}"
        ) from error
    if present < 1 or vblank < 1:
        raise ValueError(f"invalid {label} marker: {markers[0]}")
    return {"present": present, "vblank": vblank}


def read_pause_checkpoint(content):
    return read_route_checkpoint(content, PAUSE_MARKER, "pause checkpoint")


def read_mission_activation(content):
    return read_route_checkpoint(
        content, MISSION_ACTIVE_MARKER, "mission activation"
    )


def read_jsonl(path, category=None):
    events = []
    sequence = 0
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"{path}:{line_number}: invalid JSON: {error}"
                ) from error
            if event.get("sequence") != sequence:
                raise ValueError(
                    f"{path}:{line_number}: non-consecutive event sequence"
                )
            sequence += 1
            if category is None or event.get("category") == category:
                events.append(event)
    if sequence == 0:
        raise ValueError(f"{path}: structured runtime log is empty")
    return events


def validate_module_lifecycle(events):
    active = {}
    seen_bases = set()
    reused_bases = set()
    unload_count = 0
    mission_loaded = False

    for event in events:
        if event.get("category") != "module":
            continue
        action = event.get("event")
        if action in ("load_failed", "unload_failed"):
            raise ValueError(
                f"module lifecycle contains {action}: "
                f"{event.get('path', '')}"
            )
        uid = event.get("uid")
        if action == "loaded":
            base = int(event["base"], 0)
            size = int(event["size"])
            end = base + size
            if base:
                for current in active.values():
                    current_base = current["base"]
                    current_end = current_base + current["size"]
                    if (
                        current_base
                        and base < current_end
                        and current_base < end
                    ):
                        raise ValueError(
                            f"module {event['path']} overlaps active "
                            f"module {current['path']}"
                        )
                if base in seen_bases:
                    reused_bases.add(base)
                seen_bases.add(base)
            active[uid] = {
                "path": event["path"],
                "base": base,
                "size": size,
            }
            if event["path"] == MISSION_MODULE:
                mission_loaded = True
        elif action == "unloaded":
            current = active.pop(uid, None)
            if not current:
                raise ValueError(
                    f"module lifecycle unloads unknown UID {uid}"
                )
            if (
                current["path"] != event["path"]
                or current["base"] != int(event["base"], 0)
                or current["size"] != int(event["size"])
            ):
                raise ValueError(
                    f"module lifecycle changed identity for UID {uid}"
                )
            unload_count += 1

    required_reuse = {0x08AFB800, 0x08B86F00}
    if not mission_loaded:
        raise ValueError("mission overlay is absent from module lifecycle")
    if not required_reuse.issubset(reused_bases):
        missing = sorted(required_reuse - reused_bases)
        raise ValueError(
            "module lifecycle did not prove overlay-base reuse: "
            + ", ".join(f"0x{base:08x}" for base in missing)
        )
    return {
        "unload_count": unload_count,
        "reused_bases": [
            f"0x{base:08x}" for base in sorted(reused_bases)
        ],
    }


def _hex32(value):
    return f"0x{value:08x}"


def _uid(value):
    return f"0x{value:x}"


def expected_plaintext_module_lifecycle(modules):
    expected = []
    for key in ("zlib", "sound2", "kjfs"):
        module = modules[key]
        uid = module["uid"]
        common_start = {
            "path": module["path"],
            "uid": _uid(uid),
            "entry": _hex32(module["entry"]),
            "gp": _hex32(module["gp"]),
            "argument_size": 0,
            "argument_address": _hex32(0),
            "status_address": _hex32(0),
            "option_address": _hex32(0),
            "status": _hex32(0),
        }
        expected.append(
            {
                "category": "module",
                "event": "loaded",
                "path": module["path"],
                "uid": _uid(uid),
                "base": _hex32(module["base"]),
                "size": module["size"],
                "entry": _hex32(module["entry"]),
                "gp": _hex32(module["gp"]),
                "module_start": _hex32(module["module_start"]),
                "module_stop": _hex32(module["module_stop"]),
                "start_priority": module["start_priority"],
                "start_stack_size": module["start_stack_size"],
                "start_attributes": _hex32(
                    module["start_attributes"]
                ),
                "result": _hex32(uid),
            }
        )
        expected.append(
            {
                "category": "module",
                "event": "start_requested",
                **common_start,
                "result": _hex32(0),
            }
        )

        start_thread = module.get("start_thread")
        if start_thread:
            thread_common = {
                "uid": _uid(start_thread["uid"]),
                "name": start_thread["name"],
                "entry": _hex32(module["entry"]),
                "priority": module["start_priority"],
                "stack_start": _hex32(start_thread["stack_start"]),
                "stack_size": start_thread["stack_size"],
                "attributes": _hex32(start_thread["attributes"]),
                "argument_size": 0,
                "argument_address": _hex32(0),
            }
            expected.append(
                {
                    "category": "thread",
                    "event": "created",
                    **thread_common,
                    "gp": _hex32(start_thread["creation_gp"]),
                    "sp": _hex32(0),
                    "k0": _hex32(0),
                    "ra": _hex32(0),
                    "exit_status": _hex32(0x800201A4),
                    "result": _hex32(start_thread["uid"]),
                }
            )
            started_thread = {
                "category": "thread",
                "event": "started",
                **thread_common,
                "gp": _hex32(module["gp"]),
                "sp": _hex32(start_thread["sp"]),
                "k0": _hex32(start_thread["k0"]),
                "ra": _hex32(start_thread["ra"]),
                "exit_status": _hex32(0x800201A4),
                "result": _hex32(0),
            }
            expected.append(started_thread)

            for worker in module.get("worker_threads", []):
                expected.append(
                    {
                        "category": "thread",
                        "event": "created",
                        "uid": _uid(worker["uid"]),
                        "name": worker["name"],
                        "entry": _hex32(worker["entry"]),
                        "priority": worker["priority"],
                        "stack_start": _hex32(worker["stack_start"]),
                        "stack_size": worker["stack_size"],
                        "attributes": _hex32(worker["attributes"]),
                        "gp": _hex32(module["gp"]),
                        "argument_size": 0,
                        "argument_address": _hex32(0),
                        "sp": _hex32(0),
                        "k0": _hex32(0),
                        "ra": _hex32(0),
                        "exit_status": _hex32(0x800201A4),
                        "result": _hex32(worker["uid"]),
                    }
                )

            expected.append(
                {
                    **started_thread,
                    "event": "deleted",
                    "exit_status": _hex32(
                        start_thread["exit_status"]
                    ),
                }
            )

        expected.append(
            {
                "category": "module",
                "event": "started",
                **common_start,
                "result": _hex32(uid),
            }
        )
    return expected


def validate_plaintext_module_lifecycle(events, modules):
    expected = expected_plaintext_module_lifecycle(modules)
    first_path = modules["zlib"]["path"]
    last_path = modules["kjfs"]["path"]
    try:
        start = next(
            index
            for index, event in enumerate(events)
            if event.get("category") == "module"
            and event.get("event") == "loaded"
            and event.get("path") == first_path
        )
        end = next(
            index
            for index, event in enumerate(events[start:], start)
            if event.get("category") == "module"
            and event.get("event") == "started"
            and event.get("path") == last_path
        )
    except StopIteration as error:
        raise ValueError(
            "plaintext module lifecycle is incomplete"
        ) from error

    observed = [
        event
        for event in events[start:end + 1]
        if event.get("category") in ("module", "thread")
    ]
    if len(observed) != len(expected):
        raise ValueError(
            "plaintext module lifecycle event count "
            f"{len(observed)} != expected {len(expected)}"
        )
    for index, (event, contract) in enumerate(
        zip(observed, expected), 1
    ):
        for field, value in contract.items():
            if event.get(field) != value:
                raise ValueError(
                    f"plaintext module lifecycle event {index} "
                    f"{field} {event.get(field)!r} != {value!r}"
                )
    return {
        "modules": ["ZLIB", "KCEJ_SOUND2", "KCEJ_FS"],
        "callback_threads": [
            _uid(modules["zlib"]["start_thread"]["uid"]),
            _uid(modules["kjfs"]["start_thread"]["uid"]),
        ],
        "worker_threads": [
            _uid(worker["uid"])
            for worker in modules["kjfs"]["worker_threads"]
        ],
    }


def expected_plaintext_module_stops(modules):
    expected = []
    for key in ("kjfs", "sound2", "zlib"):
        module = modules[key]
        uid = module["uid"]
        common_stop = {
            "path": module["path"],
            "uid": _uid(uid),
            "entry": _hex32(module["module_stop"]),
            "gp": _hex32(module["gp"]),
            "argument_size": 0,
            "argument_address": _hex32(0),
            "status_address": _hex32(0),
            "option_address": _hex32(0),
            "status": _hex32(0),
        }
        expected.append(
            {
                "category": "module",
                "event": "stop_requested",
                **common_stop,
                "result": _hex32(0),
            }
        )

        stop_thread = module.get("stop_thread")
        if stop_thread:
            thread_common = {
                "uid": _uid(stop_thread["uid"]),
                "name": stop_thread["name"],
                "entry": _hex32(module["module_stop"]),
                "priority": 0x20,
                "stack_start": _hex32(stop_thread["stack_start"]),
                "stack_size": stop_thread["stack_size"],
                "attributes": _hex32(stop_thread["attributes"]),
                "argument_size": 0,
                "argument_address": _hex32(0),
            }
            expected.append(
                {
                    "category": "thread",
                    "event": "created",
                    **thread_common,
                    "gp": _hex32(stop_thread["creation_gp"]),
                    "sp": _hex32(0),
                    "k0": _hex32(0),
                    "ra": _hex32(0),
                    "exit_status": _hex32(0x800201A4),
                    "result": _hex32(stop_thread["uid"]),
                }
            )
            started_thread = {
                "category": "thread",
                "event": "started",
                **thread_common,
                "gp": _hex32(module["gp"]),
                "sp": _hex32(stop_thread["sp"]),
                "k0": _hex32(stop_thread["k0"]),
                "ra": _hex32(stop_thread["ra"]),
                "exit_status": _hex32(0x800201A4),
                "result": _hex32(0),
            }
            expected.append(started_thread)
            expected.append(
                {
                    **started_thread,
                    "event": "deleted",
                    "exit_status": _hex32(
                        stop_thread["exit_status"]
                    ),
                }
            )

        expected.append(
            {
                "category": "module",
                "event": "stopped",
                **common_stop,
                "result": _hex32(0),
            }
        )
    return expected


def validate_plaintext_module_stops(events, modules):
    expected = expected_plaintext_module_stops(modules)
    first_path = modules["kjfs"]["path"]
    last_path = modules["zlib"]["path"]
    try:
        start = next(
            index
            for index, event in enumerate(events)
            if event.get("category") == "module"
            and event.get("event") == "stop_requested"
            and event.get("path") == first_path
        )
        end = next(
            index
            for index, event in enumerate(events[start:], start)
            if event.get("category") == "module"
            and event.get("event") == "stopped"
            and event.get("path") == last_path
        )
    except StopIteration as error:
        raise ValueError(
            "plaintext module stop lifecycle is incomplete"
        ) from error

    observed = [
        event
        for event in events[start:end + 1]
        if event.get("category") in ("module", "thread")
    ]
    if len(observed) != len(expected):
        raise ValueError(
            "plaintext module stop event count "
            f"{len(observed)} != expected {len(expected)}"
        )
    for index, (event, contract) in enumerate(
        zip(observed, expected), 1
    ):
        for field, value in contract.items():
            if event.get(field) != value:
                raise ValueError(
                    f"plaintext module stop event {index} "
                    f"{field} {event.get(field)!r} != {value!r}"
                )
    return {
        "stop_order": ["KCEJ_FS", "KCEJ_SOUND2", "ZLIB"],
        "callback_threads": [
            _uid(modules["kjfs"]["stop_thread"]["uid"]),
            _uid(modules["zlib"]["stop_thread"]["uid"]),
        ],
        "callback_status": _hex32(0),
    }


def read_interpreter_profile(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) < 3 or lines[0] != "# psp-recomp interpreter profile v1":
        raise ValueError(f"{path}: invalid interpreter profile")
    expected_header = (
        "module\ttarget\tcalls\tinstructions\tsyscalls\t"
        "native_handoffs\tstep_limits\treturns\tfailures"
    )
    if lines[1] != expected_header:
        raise ValueError(f"{path}: unexpected interpreter profile header")

    records = []
    for line_number, line in enumerate(lines[2:], 3):
        fields = line.split("\t")
        if len(fields) != 9:
            raise ValueError(
                f"{path}:{line_number}: expected 9 profile fields"
            )
        try:
            values = [int(value, 0) for value in fields[2:]]
        except ValueError as error:
            raise ValueError(
                f"{path}:{line_number}: invalid profile counter"
            ) from error
        record = {
            "module": fields[0],
            "target": fields[1],
            "calls": values[0],
            "instructions": values[1],
            "syscalls": values[2],
            "native_handoffs": values[3],
            "step_limits": values[4],
            "returns": values[5],
            "failures": values[6],
        }
        if record["failures"]:
            raise ValueError(
                f"{path}:{line_number}: interpreter target did not "
                "complete cleanly"
            )
        records.append(record)
    if not records:
        raise ValueError(f"{path}: interpreter profile has no targets")

    modules = {}
    for record in records:
        totals = modules.setdefault(
            record["module"],
            {"calls": 0, "instructions": 0},
        )
        totals["calls"] += record["calls"]
        totals["instructions"] += record["instructions"]
    module_totals = [
        {"module": module, **totals}
        for module, totals in modules.items()
    ]
    module_totals.sort(
        key=lambda item: (-item["instructions"], item["module"])
    )
    records.sort(
        key=lambda item: (
            -item["instructions"],
            item["module"],
            item["target"],
        )
    )
    return {
        "total_calls": sum(record["calls"] for record in records),
        "total_instructions": sum(
            record["instructions"] for record in records
        ),
        "total_step_limits": sum(
            record["step_limits"] for record in records
        ),
        "modules": module_totals,
        "top_targets": records[:10],
    }


def run_smoke(argv):
    args = parse_args(argv)
    with args.config.open("rb") as stream:
        settings = tomllib.load(stream)
    config = settings["smoke"]["first_mission"]
    plaintext_modules = settings["plaintext_modules"]
    route_setting = args.route or Path(config["route"])
    present = (
        args.present
        if args.present is not None
        else config["present"]
    )
    analog_start = config.get("analog_start", 6200)
    analog_end = config.get("analog_end", max(analog_start, present - 100))
    expected_frame_sha256 = (
        args.expected_frame_sha256
    )
    frame_region = config.get("frame_region")
    expected_frame_region_sha256 = (
        args.expected_frame_region_sha256
        or config.get(
            "native_frame_region_sha256"
            if args.native_zlib
            else "frame_region_sha256"
        )
    )
    if bool(frame_region) != bool(expected_frame_region_sha256):
        raise ValueError(
            "frame_region and frame_region_sha256 must be configured together"
        )
    executable = args.executable.resolve()
    iso = args.iso.resolve()
    route = (
        route_setting
        if route_setting.is_absolute()
        else ROOT / route_setting
    ).resolve()
    output = args.out.resolve()
    if present < 1:
        raise ValueError("--present must be positive")
    if args.timeout < 1:
        raise ValueError("--timeout must be positive")
    if analog_start < 0 or analog_end < analog_start or analog_end >= present:
        raise ValueError(
            "first-mission analog interval must precede the checkpoint"
        )
    for path, label in (
        (executable, "runtime executable"),
        (iso, "supported ISO"),
        (route, "pad route"),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label} does not exist: {path}")
    if output.exists():
        raise FileExistsError(f"output directory already exists: {output}")

    output.mkdir(parents=True)
    memstick = output / "memstick"
    memstick.mkdir()
    capture = output / "capture_first_mission_pause.ppm"
    log_path = output / "runtime.log"
    structured_log_path = output / "runtime.jsonl"
    profile_path = output / "interpreter-profile.tsv"
    environment = os.environ.copy()
    environment.update(
        {
            "PSP_ISO": str(iso),
            "SR_PADSCRIPT": str(route),
            "SR_GRAPHICS_CONFIG": "0",
            "SR_GPU": args.renderer,
            "SR_NO_DIALOGS": "1",
            "MGSPO_OSK_TEXT": "PLAYER",
            "SR_MEMSTICK": str(memstick),
            "SR_EXIT_AFTER_PRESENT": str(present),
            "SR_MODLOG": "1",
            "SR_MODULE_LOG": "1",
            "MGSPO_LOG_CATEGORIES": "module,thread,fatal",
            "MGSPO_ENABLE_NATIVE_ZLIB": "1" if args.native_zlib else "0",
            "MGSPO_AUTOMATE_FIRST_MISSION": "1",
            "MGSPO_FIRST_MISSION_CAPTURE": str(capture),
            "SR_INTERP_PROFILE": str(profile_path),
            "SR_ANALOG": "128,0",
            "SR_ANALOG_START": str(analog_start),
            "SR_ANALOG_END": str(analog_end),
        }
    )
    if args.turbo:
        environment["SR_NOVBPACE"] = "1"
    else:
        environment.pop("SR_NOVBPACE", None)

    started = time.monotonic()
    with log_path.open("w", encoding="utf-8", newline="") as log:
        process = subprocess.run(
            [str(executable), "--log", str(structured_log_path)],
            cwd=output,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=args.timeout,
            check=False,
        )
    elapsed = time.monotonic() - started
    content = log_path.read_text(encoding="utf-8", errors="replace")
    if process.returncode != 0:
        raise RuntimeError(
            f"runtime exited with code {process.returncode}; see {log_path}"
        )
    validate_log(content, present, args.native_zlib, args.renderer)
    mission_activation = read_mission_activation(content)
    pause_checkpoint = read_pause_checkpoint(content)
    if (
        mission_activation["present"] >= pause_checkpoint["present"]
        or mission_activation["vblank"] >= pause_checkpoint["vblank"]
    ):
        raise ValueError("mission activation did not precede the pause checkpoint")
    if pause_checkpoint["present"] >= present:
        raise ValueError(
            "pause checkpoint did not precede the presentation limit"
        )
    events = read_jsonl(structured_log_path)
    fatal_events = [
        event for event in events
        if event.get("category") == "fatal"
    ]
    if fatal_events:
        raise ValueError(
            "structured runtime log contains fatal events: "
            + ", ".join(
                event.get("event", "unknown")
                for event in fatal_events
            )
        )
    lifecycle = validate_module_lifecycle(events)
    plaintext_lifecycle = validate_plaintext_module_lifecycle(
        events, plaintext_modules
    )
    interpreter_profile = read_interpreter_profile(profile_path)
    interpreted_zlib = any(
        module["module"] == "ZLIB"
        for module in interpreter_profile["modules"]
    )
    if args.native_zlib and interpreted_zlib:
        raise ValueError(
            "native ZLIB fell back to interpreted execution"
        )
    if not args.native_zlib and not interpreted_zlib:
        raise ValueError(
            "interpreted ZLIB did not appear in the execution profile"
        )

    if not capture.is_file():
        raise FileNotFoundError(f"checkpoint capture was not written: {capture}")
    frame_sha256 = sha256_file(capture)
    frame_region_sha256 = (
        sha256_ppm_region(capture, frame_region)
        if frame_region
        else None
    )
    if (
        expected_frame_sha256
        and frame_sha256.lower() != expected_frame_sha256.lower()
    ):
        raise ValueError(
            f"frame SHA-256 {frame_sha256} != expected "
            f"{expected_frame_sha256.lower()}"
        )
    if (
        expected_frame_region_sha256
        and frame_region_sha256.lower()
        != expected_frame_region_sha256.lower()
    ):
        raise ValueError(
            f"frame region SHA-256 {frame_region_sha256} != expected "
            f"{expected_frame_region_sha256.lower()}"
        )

    save = (
        memstick
        / "PSP"
        / "SAVEDATA"
        / "ULUS10202001"
        / "PARAM.SFO"
    )
    if not save.is_file():
        raise FileNotFoundError(f"clean-route savedata was not created: {save}")

    summary = {
        "presentation_limit": present,
        "mission_activation": mission_activation,
        "pause_checkpoint": pause_checkpoint,
        "frame_sha256": frame_sha256,
        "frame_region": frame_region,
        "frame_region_sha256": frame_region_sha256,
        "mission_module": MISSION_MODULE,
        "mission_base": f"0x{MISSION_BASE}",
        "savedata": "ULUS10202001",
        "renderer": args.renderer,
        "zlib_mode": "native" if args.native_zlib else "interpreter",
        "module_lifecycle": lifecycle,
        "plaintext_module_lifecycle": plaintext_lifecycle,
        "interpreter_profile": interpreter_profile,
        "elapsed_seconds": round(elapsed, 3),
    }
    summary_path = output / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    if not args.keep_structured_log:
        structured_log_path.unlink()
    print(
        "OK: clean-save route reached the stable first-mission pause "
        f"checkpoint; frame region SHA-256 {frame_region_sha256}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(run_smoke(sys.argv))
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)

#!/usr/bin/env python3
"""Verify plaintext module start, worker, and stop lifecycle behavior."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import tomllib

from smoke import (
    DEFAULT_CONFIG,
    read_jsonl,
    validate_plaintext_module_lifecycle,
    validate_plaintext_module_stops,
)

STOP_MARKER = "plaintext module stop checkpoint reached"


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("iso", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--keep-structured-log", action="store_true")
    parser.add_argument(
        "--interpreted-zlib",
        action="store_true",
        help="use interpreter fallback instead of generated ZLIB code",
    )
    return parser.parse_args(argv[1:])


def run_probe(argv):
    args = parse_args(argv)
    with args.config.open("rb") as stream:
        modules = tomllib.load(stream)["plaintext_modules"]
    executable = args.executable.resolve()
    iso = args.iso.resolve()
    output = args.out.resolve()
    if args.timeout < 1:
        raise ValueError("--timeout must be positive")
    for path, label in (
        (executable, "runtime executable"),
        (iso, "supported ISO"),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label} does not exist: {path}")
    if output.exists():
        raise FileExistsError(f"output directory already exists: {output}")

    output.mkdir(parents=True)
    memstick = output / "memstick"
    memstick.mkdir()
    text_log = output / "runtime.log"
    structured_log = output / "runtime.jsonl"
    environment = os.environ.copy()
    environment.update(
        {
            "PSP_ISO": str(iso),
            "SR_GRAPHICS_CONFIG": "0",
            "SR_GPU": "sw",
            "SR_NO_DIALOGS": "1",
            "SR_MEMSTICK": str(memstick),
            "MGSPO_LOG_CATEGORIES": "module,thread,fatal",
            "MGSPO_VERIFY_PLAINTEXT_STOPS": "1",
            "MGSPO_ENABLE_NATIVE_ZLIB": (
                "0" if args.interpreted_zlib else "1"
            ),
        }
    )

    started = time.monotonic()
    with text_log.open("w", encoding="utf-8", newline="") as log:
        process = subprocess.run(
            [str(executable), "--log", str(structured_log)],
            cwd=output,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=args.timeout,
            check=False,
        )
    elapsed = time.monotonic() - started
    content = text_log.read_text(encoding="utf-8", errors="replace")
    if process.returncode != 0:
        raise RuntimeError(
            f"runtime exited with code {process.returncode}; "
            f"see {text_log}"
        )
    if content.count(STOP_MARKER) != 1:
        raise ValueError("plaintext module stop checkpoint is absent")

    events = read_jsonl(structured_log)
    fatal_events = [
        event
        for event in events
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
    start_contract = validate_plaintext_module_lifecycle(events, modules)
    stop_contract = validate_plaintext_module_stops(events, modules)
    summary = {
        "zlib_mode": (
            "interpreter" if args.interpreted_zlib else "native"
        ),
        "start_lifecycle": start_contract,
        "stop_lifecycle": stop_contract,
        "elapsed_seconds": round(elapsed, 3),
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    if not args.keep_structured_log:
        structured_log.unlink()
    print(
        "OK: plaintext module start, worker, and stop lifecycle "
        "matches the measured contract"
    )
    return 0


def main(argv=None):
    try:
        return run_probe(argv or sys.argv)
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Verify that generation uses the exact pinned psp-recomp submodule."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[2]
IDENTITY_FILE = "mgspo_toolkit_identity.json"


def git_output(toolkit, *arguments):
    return subprocess.run(
        ["git", "-C", str(toolkit), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def identify_toolkit(toolkit, expected_commit):
    toolkit = toolkit.resolve()
    if not (toolkit / "tools" / "codegen.py").is_file():
        raise ValueError(f"psp-recomp tools were not found under {toolkit}")
    root = git_output(toolkit, "rev-parse", "--show-toplevel")
    if root.returncode or Path(root.stdout.strip()).resolve() != toolkit:
        raise ValueError(f"{toolkit} is not a verifiable Git checkout")
    revision = git_output(toolkit, "rev-parse", "--verify", "HEAD")
    status = git_output(
        toolkit,
        "status",
        "--porcelain=v1",
        "--untracked-files=normal",
        "--ignore-submodules=none",
    )
    if revision.returncode or status.returncode:
        raise ValueError("could not inspect psp-recomp revision and status")
    actual_commit = revision.stdout.strip()
    if actual_commit != expected_commit:
        raise ValueError(
            f"psp-recomp is at {actual_commit}, expected {expected_commit}"
        )
    if status.stdout.strip():
        raise ValueError("psp-recomp has uncommitted changes")
    return {
        "schema": 1,
        "expected_commit": expected_commit,
        "revision": actual_commit,
        "dirty": False,
    }


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toolkit", type=Path, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "config" / "mgspo.toml",
    )
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args(argv)
    try:
        with args.config.open("rb") as stream:
            config = tomllib.load(stream)
        identity = identify_toolkit(
            args.toolkit,
            config["runtime"]["commit"],
        )
        if args.manifest is not None:
            recorded = json.loads(args.manifest.read_text(encoding="utf-8"))
            if recorded != identity:
                raise ValueError(
                    f"toolkit identity differs from {args.manifest}; regenerate"
                )
        return 0
    except (
        json.JSONDecodeError,
        KeyError,
        OSError,
        tomllib.TOMLDecodeError,
        ValueError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

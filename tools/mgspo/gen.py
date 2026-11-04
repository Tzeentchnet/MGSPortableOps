#!/usr/bin/env python3
"""Analyze and generate cached native C for Portable Ops' main PRX."""

import argparse
import filecmp
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import tomllib

from iso9660 import sha1_file
from toolkit_identity import IDENTITY_FILE, identify_toolkit

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TOOLKIT = ROOT / "external" / "psp-recomp"
SOURCE_MANIFEST = "mgspo_generated_sources.txt"


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--toolkit",
        type=Path,
        default=Path(os.environ.get("PSP_RECOMP_DIR", DEFAULT_TOOLKIT)),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "build" / "mgspo" / "gen",
    )
    return parser.parse_args(argv[1:])


def run(command, *, env, stderr=None):
    command_text = [os.fspath(part) for part in command]
    print(f"> {subprocess.list2cmdline(command_text)}")
    return subprocess.run(
        command_text,
        check=False,
        env=env,
        stderr=stderr,
    )


def prepare_environment():
    env = dict(os.environ)
    if not env.get("PSP_RECOMP_CODEGEN_CACHE"):
        local_app_data = env.get("LOCALAPPDATA")
        if local_app_data:
            env["PSP_RECOMP_CODEGEN_CACHE"] = os.fspath(
                Path(local_app_data) / "psp-recomp" / "codegen-cache"
            )
    return env


def verify_prx(prx, expected_sha1):
    if not prx.is_file():
        raise ValueError(
            f"missing {prx}; run tools\\mgspo\\extract.py <ISO> first"
        )
    actual_sha1 = sha1_file(prx)
    if actual_sha1 != expected_sha1:
        raise ValueError(
            f"SHA-1 mismatch for {prx}: {actual_sha1} != {expected_sha1}; "
            "rerun extraction"
        )


def validate_generated_control_flow(chunks):
    function_pattern = re.compile(
        r"^void (f_[0-9a-f]{8})\(CpuState \*s\) \{$"
    )
    goto_pattern = re.compile(r"\bgoto (L_[0-9a-f]{8});")
    label_pattern = re.compile(r"^\s*(L_[0-9a-f]{8}):")
    failures = []
    for path in chunks:
        current = None
        gotos = set()
        labels = set()

        def finish():
            if current:
                for label in sorted(gotos - labels):
                    failures.append(f"{path.name}: {current} misses {label}")

        for line in path.read_text(encoding="utf-8").splitlines():
            match = function_pattern.match(line)
            if match:
                finish()
                current = match.group(1)
                gotos = set()
                labels = set()
            if current:
                gotos.update(goto_pattern.findall(line))
                label = label_pattern.match(line)
                if label:
                    labels.add(label.group(1))
        finish()
    if failures:
        raise ValueError(
            "generated control flow has unresolved labels: "
            + "; ".join(failures)
        )


def generate(args):
    config_path = ROOT / "config" / "mgspo.toml"
    with config_path.open("rb") as stream:
        config = tomllib.load(stream)

    tools = args.toolkit / "tools"
    codegen = ROOT / "tools" / "mgspo" / "codegen.py"
    if not (tools / "codegen.py").is_file():
        raise ValueError(
            f"psp-recomp tools were not found under {args.toolkit}"
        )
    identity = identify_toolkit(
        args.toolkit,
        config["runtime"]["commit"],
    )

    module = config["module"]
    disc_dir = ROOT / "build" / "mgspo" / "disc"
    prx = disc_dir / Path(module["file"])
    expected_sha1 = config["disc"]["files"][module["file"]]
    verify_prx(prx, expected_sha1)

    output = args.out.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    env = prepare_environment()
    with tempfile.TemporaryDirectory(
        prefix=".mgspo-gen-", dir=output.parent
    ) as temporary:
        staging = Path(temporary) / "gen"
        staging.mkdir(parents=True)

        commands = [
            [
                sys.executable,
                tools / "prxload.py",
                prx,
                f"{module['base']:#x}",
                f"--out={staging / 'mgspo_image.bin'}",
            ],
            [
                sys.executable,
                tools / "imports.py",
                prx,
                f"{module['base']:#x}",
                f"--toml={staging / 'mgspo_imports.toml'}",
            ],
            [
                sys.executable,
                tools / "analyze.py",
                prx,
                f"--base={module['base']:#x}",
                f"--toml={staging / 'mgspo_functions.toml'}",
                "--quiet",
            ],
        ]
        for command in commands:
            result = run(command, env=env)
            if result.returncode:
                return result.returncode

        codegen_command = [
            sys.executable,
            codegen,
            "--toolkit",
            args.toolkit,
            prx,
            staging / "mgspo_recomp.c",
            f"--base={module['base']:#x}",
        ]
        codegen_command.extend(
            f"--function-entry={address:#x}"
            for address in module.get("function_entries", [])
        )
        codegen_command.append("--split")
        log_path = staging / "codegen.log"
        with log_path.open("w", encoding="utf-8") as log:
            result = run(codegen_command, env=env, stderr=log)
        print(log_path.read_text(encoding="utf-8"), end="")
        if result.returncode:
            return result.returncode
        stubs = staging / "stubs.txt"
        if stubs.exists():
            print(
                f"ERROR: trapping stubs were emitted; see {stubs}",
                file=sys.stderr,
            )
            return 1

        header = staging / "mgspo_recomp.h"
        register = staging / "mgspo_recomp_register.c"
        chunks = sorted(
            staging.glob("mgspo_recomp_[0-9][0-9][0-9].c")
        )
        if not header.is_file() or not register.is_file() or not chunks:
            raise ValueError("split generation did not produce a complete output")
        validate_generated_control_flow(chunks)
        sources = [
            path.relative_to(staging).as_posix()
            for path in [*chunks, register]
        ]
        if identify_toolkit(
            args.toolkit,
            config["runtime"]["commit"],
        ) != identity:
            raise ValueError("psp-recomp changed during generation; retry")
        (staging / IDENTITY_FILE).write_text(
            json.dumps(identity, indent=2) + "\n",
            encoding="utf-8",
        )
        publish_generation(staging, output, sources)
        print(
            f"wrote {output / SOURCE_MANIFEST} "
            f"({len(sources)} translation units)"
        )
    return 0


def publish_generation(staging, output, sources):
    output.mkdir(parents=True, exist_ok=True)
    manifest = output / SOURCE_MANIFEST
    old_sources = set()
    if manifest.is_file():
        old_sources = {
            line.strip()
            for line in manifest.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    manifest.unlink(missing_ok=True)
    for path in sorted(path for path in staging.rglob("*") if path.is_file()):
        destination = output / path.relative_to(staging)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_file() and filecmp.cmp(
            path, destination, shallow=False
        ):
            continue
        os.replace(path, destination)
    for stale in old_sources - set(sources):
        if re.fullmatch(
            r"mgspo_recomp_(?:[0-9][0-9][0-9]|register)\.c",
            stale,
        ):
            (output / stale).unlink(missing_ok=True)
    temporary_manifest = output / f".{SOURCE_MANIFEST}.tmp"
    temporary_manifest.write_text(
        "\n".join(sources) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary_manifest, manifest)


def main(argv):
    args = parse_args(argv)
    try:
        return generate(args)
    except (
        KeyError,
        OSError,
        tomllib.TOMLDecodeError,
        ValueError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

#!/usr/bin/env python3
"""Prepare, capture, and compare the pinned PPSSPP boot oracle."""

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "mgspo.toml"
DEFAULT_ORACLE_ROOT = ROOT / "build" / "mgspo" / "oracle"
DEFAULT_CHECKOUT = DEFAULT_ORACLE_ROOT / "ppsspp"
DEFAULT_BUILD = DEFAULT_CHECKOUT / "build-oracle"
TRACE_LIMIT_MAX = 50_000_000
SUPPORTED_TRACE_FORMAT = 1
CAPTURE_FILES = (
    "boot_state.json",
    "cpu.trace",
    "events.jsonl",
    "stack.bin",
    "trace.done",
)

EXPECTED_BUILD = {
    "target": "PPSSPPHeadless",
    "generator": "Ninja",
    "configuration": "Release",
    "architecture": "x64",
    "compiler": "msvc",
}

EXPECTED_SETTINGS = {
    "cpu_core": "interpreter",
    "graphics": "software",
    "sound": False,
    "fast_forward": True,
    "ignore_bad_memory_access": True,
    "software_renderer_jit": True,
    "vertex_decoder_jit": True,
    "force_hle": True,
    "psp_model": "slim",
    "firmware_version": 660,
    "language": "english",
    "time_format": "24h",
    "date_format": "ddmmyyyy",
    "timezone_minutes": 60,
    "rtc_epoch_seconds": 946684800,
    "button_preference": "cross",
    "nickname": "shadow",
    "parental_level": 9,
    "memstick_inserted": True,
    "memstick_size_gb": 16,
    "wlan": True,
    "mac_address": "12:34:56:78:9A:BC",
}

VERIFIED_START_FIELDS = {
    "module_uid": int,
    "uid": int,
    "priority": int,
    "stack_start": int,
    "stack_size": int,
    "attr": int,
    "effective_attr": int,
    "next_uid": int,
    "initial_ge_list_id": int,
    "initial_hcount": int,
    "argument_hex": str,
    "argument_address": int,
    "initial_sp": int,
    "initial_k0": int,
    "initial_ra": int,
    "initial_gpr_fill": int,
    "initial_hi": int,
    "initial_lo": int,
    "initial_fcr31": int,
    "initial_fpcond": int,
    "initial_fpr_fill_bits": int,
    "initial_vfpu_fill_bits": int,
    "prepared_stack_sha256": str,
    "initial_vfpu_control": list,
}


class OracleError(ValueError):
    pass


@dataclass(frozen=True)
class OracleConfig:
    root: Path
    config_path: Path
    repository: str
    version: str
    commit: str
    patch: Path
    trace_format: int
    trace_steps: int
    build: dict
    settings: dict
    module: dict
    disc: dict


def _mapping(value, name):
    if not isinstance(value, dict):
        raise OracleError(f"{name} must be a table")
    return value


def _string(value, name):
    if not isinstance(value, str) or not value:
        raise OracleError(f"{name} must be a nonempty string")
    return value


def _integer(value, name, minimum=0, maximum=0xFFFFFFFF):
    if isinstance(value, bool) or not isinstance(value, int):
        raise OracleError(f"{name} must be an integer")
    if value < minimum or value > maximum:
        raise OracleError(
            f"{name} must be between {minimum} and {maximum}"
        )
    return value


def _inside_root(root, path):
    try:
        path.relative_to(root)
    except ValueError as error:
        raise OracleError(f"{path} is outside repository root {root}") from error


def validate_config(data, config_path=DEFAULT_CONFIG, root=ROOT):
    root = root.resolve()
    config_path = config_path.resolve()
    oracle = _mapping(data.get("oracle"), "oracle")
    ppsspp = _mapping(oracle.get("ppsspp"), "oracle.ppsspp")

    repository = _string(
        ppsspp.get("repository"),
        "oracle.ppsspp.repository",
    )
    if repository != "https://github.com/hrydgard/ppsspp.git":
        raise OracleError("oracle.ppsspp.repository is not the supported URL")

    version = _string(ppsspp.get("version"), "oracle.ppsspp.version")
    commit = _string(ppsspp.get("commit"), "oracle.ppsspp.commit")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise OracleError(
            "oracle.ppsspp.commit must be 40 lowercase hexadecimal digits"
        )

    patch_setting = _string(
        ppsspp.get("patch"),
        "oracle.ppsspp.patch",
    )
    patch_relative = Path(patch_setting)
    if patch_relative.is_absolute():
        raise OracleError("oracle.ppsspp.patch must be repository-relative")
    patch = (root / patch_relative).resolve()
    _inside_root(root, patch)

    trace_format = _integer(
        ppsspp.get("trace_format"),
        "oracle.ppsspp.trace_format",
        1,
        SUPPORTED_TRACE_FORMAT,
    )
    if trace_format != SUPPORTED_TRACE_FORMAT:
        raise OracleError(
            f"unsupported trace format {trace_format}; "
            f"expected {SUPPORTED_TRACE_FORMAT}"
        )
    trace_steps = _integer(
        ppsspp.get("trace_steps"),
        "oracle.ppsspp.trace_steps",
        1,
        TRACE_LIMIT_MAX,
    )

    build = _mapping(ppsspp.get("build"), "oracle.ppsspp.build")
    for key, expected in EXPECTED_BUILD.items():
        if build.get(key) != expected:
            raise OracleError(
                f"oracle.ppsspp.build.{key} must be {expected!r}"
            )
    options = build.get("cmake_options")
    if options != ["HEADLESS=ON"]:
        raise OracleError(
            "oracle.ppsspp.build.cmake_options must be ['HEADLESS=ON']"
        )

    settings = _mapping(
        ppsspp.get("settings"),
        "oracle.ppsspp.settings",
    )
    for key, expected in EXPECTED_SETTINGS.items():
        if settings.get(key) != expected:
            raise OracleError(
                f"oracle.ppsspp.settings.{key} must be {expected!r}"
            )

    module = _mapping(data.get("module"), "module")
    start = _mapping(module.get("start_thread"), "module.start_thread")
    verified = start.get("verified")
    if not isinstance(verified, bool):
        raise OracleError("module.start_thread.verified must be boolean")
    measured = set(start) - {"verified"}
    if not verified and measured:
        fields = ", ".join(sorted(measured))
        raise OracleError(
            "unverified module.start_thread contains measured fields: "
            f"{fields}"
        )
    if verified:
        missing = set(VERIFIED_START_FIELDS) - set(start)
        if missing:
            fields = ", ".join(sorted(missing))
            raise OracleError(
                f"verified module.start_thread is missing: {fields}"
            )
        for key, expected_type in VERIFIED_START_FIELDS.items():
            value = start[key]
            if expected_type is int:
                _integer(value, f"module.start_thread.{key}")
            elif not isinstance(value, expected_type):
                raise OracleError(
                    f"module.start_thread.{key} must be "
                    f"{expected_type.__name__}"
                )
        argument_hex = start["argument_hex"]
        if len(argument_hex) % 2 or not re.fullmatch(
            r"(?:[0-9a-f]{2})*",
            argument_hex,
        ):
            raise OracleError(
                "module.start_thread.argument_hex must contain whole "
                "lowercase hexadecimal bytes"
            )
        vfpu_control = start["initial_vfpu_control"]
        if len(vfpu_control) != 16:
            raise OracleError(
                "module.start_thread.initial_vfpu_control must have 16 values"
            )
        for index, value in enumerate(vfpu_control):
            _integer(
                value,
                f"module.start_thread.initial_vfpu_control[{index}]",
            )
        if not (
            start["module_uid"] < start["uid"] < start["next_uid"]
        ):
            raise OracleError(
                "module.start_thread UIDs must increase from module to "
                "thread to next_uid"
            )
        stack_end = start["stack_start"] + start["stack_size"]
        if stack_end > 0xFFFFFFFF:
            raise OracleError("module.start_thread stack range overflows")
        if start["initial_k0"] != stack_end - 0x100:
            raise OracleError(
                "module.start_thread.initial_k0 does not match stack layout"
            )
        argument_size = len(argument_hex) // 2
        if (
            start["argument_address"] + argument_size > stack_end
            or start["argument_address"] < start["stack_start"]
        ):
            raise OracleError(
                "module.start_thread argument is outside the stack"
            )
        if start["initial_sp"] + 0x40 != start["argument_address"]:
            raise OracleError(
                "module.start_thread initial SP does not match the "
                "kernel argument layout"
            )
        if start["effective_attr"] & start["attr"] != start["attr"]:
            raise OracleError(
                "module.start_thread effective attributes do not include "
                "the requested attributes"
            )
        if not re.fullmatch(
            r"[0-9a-f]{64}",
            start["prepared_stack_sha256"],
        ):
            raise OracleError(
                "module.start_thread.prepared_stack_sha256 must be a "
                "lowercase SHA-256"
            )

    disc = _mapping(data.get("disc"), "disc")
    _integer(disc.get("iso_size"), "disc.iso_size", 1, 0x7FFFFFFFFFFFFFFF)
    iso_sha1 = _string(disc.get("iso_sha1"), "disc.iso_sha1")
    if not re.fullmatch(r"[0-9a-f]{40}", iso_sha1):
        raise OracleError("disc.iso_sha1 must be a lowercase SHA-1")

    for key in ("base", "entry", "gp", "text_size", "image_size"):
        _integer(module.get(key), f"module.{key}", 1)

    return OracleConfig(
        root=root,
        config_path=config_path,
        repository=repository,
        version=version,
        commit=commit,
        patch=patch,
        trace_format=trace_format,
        trace_steps=trace_steps,
        build=dict(build),
        settings=dict(settings),
        module=dict(module),
        disc=dict(disc),
    )


def load_config(path=DEFAULT_CONFIG):
    path = path.resolve()
    try:
        with path.open("rb") as stream:
            data = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise OracleError(f"cannot load {path}: {error}") from error
    return validate_config(data, path, ROOT)


def hash_file(path, algorithm="sha256"):
    digest = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git(checkout, *arguments, text=True):
    return subprocess.run(
        ["git", "-C", str(checkout), *arguments],
        capture_output=True,
        text=text,
        encoding="utf-8" if text else None,
        errors="replace" if text else None,
        check=False,
    )


def _run(command, cwd=None, env=None):
    print("> " + subprocess.list2cmdline([str(item) for item in command]))
    result = subprocess.run(
        [str(item) for item in command],
        cwd=cwd,
        env=env,
        check=False,
    )
    if result.returncode:
        raise OracleError(
            f"command failed with exit code {result.returncode}: "
            + subprocess.list2cmdline([str(item) for item in command])
        )


def verify_checkout(config, checkout, require_patch):
    checkout = checkout.resolve()
    if not (checkout / ".git").exists():
        raise OracleError(f"{checkout} is not a Git checkout")
    top = _git(checkout, "rev-parse", "--show-toplevel")
    head = _git(checkout, "rev-parse", "HEAD")
    if top.returncode or head.returncode:
        raise OracleError(f"cannot inspect PPSSPP checkout {checkout}")
    if Path(top.stdout.strip()).resolve() != checkout:
        raise OracleError(f"{checkout} is not the PPSSPP checkout root")
    if head.stdout.strip() != config.commit:
        raise OracleError(
            f"PPSSPP is at {head.stdout.strip()}, expected {config.commit}"
        )

    status = _git(
        checkout,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--ignore-submodules=none",
    )
    if status.returncode:
        raise OracleError("cannot inspect PPSSPP working tree status")
    if not require_patch:
        if status.stdout.strip():
            raise OracleError("PPSSPP checkout is not clean")
        return

    if not config.patch.is_file():
        raise OracleError(f"PPSSPP oracle patch was not found: {config.patch}")
    reverse = _git(
        checkout,
        "apply",
        "--reverse",
        "--check",
        str(config.patch),
    )
    if reverse.returncode:
        raise OracleError(
            "PPSSPP working tree does not contain the exact oracle patch"
        )
    diff = _git(
        checkout,
        "diff",
        "--binary",
        "--full-index",
        "--no-ext-diff",
    )
    expected = config.patch.read_text(encoding="utf-8").replace("\r\n", "\n")
    actual = diff.stdout.replace("\r\n", "\n")
    if actual != expected:
        raise OracleError(
            "PPSSPP checkout contains changes beyond the oracle patch"
        )


def prepare_checkout(config, checkout):
    checkout = checkout.resolve()
    if not checkout.exists():
        checkout.parent.mkdir(parents=True, exist_ok=True)
        _run(
            [
                "git",
                "clone",
                "--filter=blob:none",
                "--no-tags",
                config.repository,
                checkout,
            ]
        )
        _run(
            [
                "git",
                "-C",
                checkout,
                "checkout",
                "--detach",
                config.commit,
            ]
        )

    status = _git(
        checkout,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--ignore-submodules=none",
    )
    if status.returncode:
        raise OracleError(f"cannot inspect PPSSPP checkout {checkout}")
    if not status.stdout.strip():
        verify_checkout(config, checkout, require_patch=False)
        if not config.patch.is_file():
            raise OracleError(
                f"PPSSPP oracle patch was not found: {config.patch}"
            )
        check = _git(checkout, "apply", "--check", str(config.patch))
        if check.returncode:
            raise OracleError(
                "oracle patch does not apply to the pinned PPSSPP checkout: "
                + check.stderr.strip()
            )
        _run(["git", "-C", checkout, "apply", str(config.patch)])

    verify_checkout(config, checkout, require_patch=True)
    _run(
        [
            "git",
            "-C",
            checkout,
            "submodule",
            "update",
            "--init",
            "--recursive",
        ]
    )
    verify_checkout(config, checkout, require_patch=True)
    print(
        f"PPSSPP {config.version} {config.commit} is patched and verified"
    )


def _visual_studio_environment():
    if os.name != "nt":
        raise OracleError("the pinned PPSSPP oracle build requires Windows")
    program_files = os.environ.get("ProgramFiles(x86)")
    if not program_files:
        raise OracleError("ProgramFiles(x86) is not set")
    vswhere = (
        Path(program_files)
        / "Microsoft Visual Studio"
        / "Installer"
        / "vswhere.exe"
    )
    if not vswhere.is_file():
        raise OracleError(f"Visual Studio locator was not found: {vswhere}")
    query = subprocess.run(
        [
            str(vswhere),
            "-latest",
            "-products",
            "*",
            "-requires",
            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
            "-property",
            "installationPath",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    installation = query.stdout.strip()
    if query.returncode or not installation:
        raise OracleError("Visual Studio 2022 C++ tools were not found")
    developer = (
        Path(installation) / "Common7" / "Tools" / "VsDevCmd.bat"
    )
    with tempfile.TemporaryDirectory(prefix="mgspo-vsenv-") as directory:
        script = Path(directory) / "environment.cmd"
        script.write_text(
            "@echo off\n"
            f'call "{developer}" -arch=x64 -host_arch=x64 >nul\n'
            "if errorlevel 1 exit /b %errorlevel%\n"
            "set\n",
            encoding="ascii",
        )
        result = subprocess.run(
            [
                os.environ.get("ComSpec", "cmd.exe"),
                "/d",
                "/c",
                str(script),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    if result.returncode:
        detail = (result.stdout + result.stderr).strip()
        raise OracleError(
            "Visual Studio developer environment failed"
            + (f": {detail}" if detail else "")
        )
    environment = {}
    for line in result.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            environment[key] = value
    path_key = next(
        (key for key in environment if key.lower() == "path"),
        "Path",
    )
    environment[path_key] = os.pathsep.join(
        entry
        for entry in environment[path_key].split(os.pathsep)
        if "winlibs" not in entry.lower()
    )
    return environment


def _command_output(command, env):
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )
    output = (result.stdout + result.stderr).strip()
    if result.returncode:
        raise OracleError(
            f"cannot identify {command[0]}: {output or result.returncode}"
        )
    return output


def _msvc_version(executable, env):
    output = _command_output([executable], env)
    for line in output.splitlines():
        if line.startswith("Microsoft ") and " Compiler Version " in line:
            return line
    raise OracleError(f"cannot parse MSVC compiler identity: {output}")


def build_headless(config, checkout, build_dir):
    checkout = checkout.resolve()
    build_dir = build_dir.resolve()
    verify_checkout(config, checkout, require_patch=True)
    environment = _visual_studio_environment()
    path_value = next(
        (
            value
            for key, value in environment.items()
            if key.lower() == "path"
        ),
        "",
    )
    tools = {}
    for executable in ("cmake", "ninja", "cl"):
        resolved = shutil.which(executable, path=path_value)
        if not resolved:
            raise OracleError(
                f"{executable} was not found in the VS build environment"
            )
        tools[executable] = resolved

    build_dir.mkdir(parents=True, exist_ok=True)
    configure = [
        tools["cmake"],
        "-S",
        checkout,
        "-B",
        build_dir,
        "-G",
        config.build["generator"],
        f"-DCMAKE_BUILD_TYPE={config.build['configuration']}",
        f"-DCMAKE_C_COMPILER={tools['cl']}",
        f"-DCMAKE_CXX_COMPILER={tools['cl']}",
    ]
    configure.extend(
        f"-D{option}" for option in config.build["cmake_options"]
    )
    _run(configure, env=environment)
    _run(
        [
            tools["cmake"],
            "--build",
            build_dir,
            "--target",
            config.build["target"],
            "--parallel",
        ],
        env=environment,
    )

    executable = build_dir / f"{config.build['target']}.exe"
    if not executable.is_file():
        raise OracleError(f"headless executable was not built: {executable}")
    compiler = _msvc_version(tools["cl"], environment)
    identity = {
        "schema": 1,
        "ppsspp_version": config.version,
        "ppsspp_commit": config.commit,
        "patch_sha256": hash_file(config.patch),
        "configuration": config.build["configuration"],
        "architecture": config.build["architecture"],
        "compiler": compiler,
        "vc_tools_version": environment.get("VCToolsVersion", "").rstrip("\\"),
        "visual_studio": environment.get("VSCMD_VER", ""),
        "windows_sdk": environment.get("WindowsSDKVersion", "").rstrip("\\"),
        "cmake": _command_output(
            [tools["cmake"], "--version"],
            environment,
        )
        .splitlines()[0],
        "ninja": _command_output(
            [tools["ninja"], "--version"],
            environment,
        ),
        "executable_sha256": hash_file(executable),
    }
    identity_path = build_dir / "mgspo_oracle_build.json"
    identity_path.write_text(
        json.dumps(identity, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {identity_path}")


def verify_iso(config, iso):
    iso = iso.resolve()
    size = iso.stat().st_size
    if size != config.disc["iso_size"]:
        raise OracleError(
            f"ISO size {size} != expected {config.disc['iso_size']}"
        )
    actual = hash_file(iso, "sha1")
    if actual != config.disc["iso_sha1"]:
        raise OracleError(
            f"ISO SHA-1 {actual} != expected {config.disc['iso_sha1']}"
        )
    return actual


def _load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise OracleError(f"cannot load {path}: {error}") from error


def verify_build_identity(config, build_identity_path, executable):
    identity = _mapping(
        _load_json(build_identity_path), "PPSSPP build identity"
    )
    _integer(identity.get("schema"), "PPSSPP build identity.schema", 1, 1)
    expected = {
        "ppsspp_version": config.version,
        "ppsspp_commit": config.commit,
        "patch_sha256": hash_file(config.patch),
        "configuration": config.build["configuration"],
        "architecture": config.build["architecture"],
        "executable_sha256": hash_file(executable),
    }
    for key, value in expected.items():
        if identity.get(key) != value:
            raise OracleError(
                f"PPSSPP build identity {key} mismatch; rebuild the oracle"
            )
    for key in (
        "compiler",
        "vc_tools_version",
        "visual_studio",
        "windows_sdk",
        "cmake",
        "ninja",
    ):
        _string(identity.get(key), f"PPSSPP build identity.{key}")
    return identity


def verify_capture(output):
    output = output.resolve()
    manifest_path = output / "manifest.json"
    manifest = _mapping(_load_json(manifest_path), "capture manifest")
    _integer(manifest.get("schema"), "capture manifest.schema", 1, 1)
    identity = _mapping(manifest.get("identity"), "capture identity")
    expected_steps = _integer(
        identity.get("trace_steps"),
        "capture identity.trace_steps",
        1,
        TRACE_LIMIT_MAX,
    )
    completion = output / "capture.complete"
    if not completion.is_file():
        raise OracleError(f"capture completion marker does not exist: {completion}")
    try:
        completion_hash = completion.read_text(encoding="ascii").strip()
    except UnicodeError as error:
        raise OracleError(f"invalid capture completion marker: {completion}") from error
    if completion_hash != hash_file(manifest_path):
        raise OracleError(f"capture completion marker does not match: {manifest_path}")

    files = _mapping(manifest.get("files"), "capture manifest.files")
    for name in CAPTURE_FILES:
        descriptor = _mapping(files.get(name), f"capture file {name}")
        size = _integer(
            descriptor.get("size"), f"capture file {name}.size", 0, 2**63 - 1
        )
        expected_hash = _string(
            descriptor.get("sha256"), f"capture file {name}.sha256"
        )
        if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            raise OracleError(f"capture file {name} has an invalid SHA-256")
        path = output / name
        if not path.is_file():
            raise OracleError(f"capture is missing {name}")
        if path.stat().st_size != size or hash_file(path) != expected_hash:
            raise OracleError(f"capture file {name} does not match its manifest")

    try:
        completed_steps = int(
            (output / "trace.done").read_text(encoding="ascii").strip()
        )
    except (UnicodeError, ValueError) as error:
        raise OracleError("invalid capture trace completion marker") from error
    if completed_steps != expected_steps:
        raise OracleError(
            f"capture trace completion reports {completed_steps} steps; "
            f"expected {expected_steps}"
        )
    return manifest


def capture_oracle(config, checkout, build_dir, iso, output):
    checkout = checkout.resolve()
    build_dir = build_dir.resolve()
    iso = iso.resolve()
    output = output.resolve()
    verify_checkout(config, checkout, require_patch=True)
    if output.exists():
        raise OracleError(f"capture output already exists: {output}")
    build_identity_path = build_dir / "mgspo_oracle_build.json"
    executable = build_dir / f"{config.build['target']}.exe"
    if not executable.is_file() or not build_identity_path.is_file():
        raise OracleError("build the pinned PPSSPPHeadless oracle first")
    build_identity = verify_build_identity(
        config, build_identity_path, executable
    )

    print(f"hashing {iso}...")
    iso_sha1 = verify_iso(config, iso)
    output.mkdir(parents=True)
    memstick = output / "memstick"
    memstick.mkdir()
    environment = os.environ.copy()
    for name in (
        "PSPRECOMP_ORACLE_KJFS_PROBE",
        "PSPRECOMP_ORACLE_KJFS_PROBE_STAGE",
        "PSPRECOMP_ORACLE_KJFS_PROBE_STOP",
        "PSPRECOMP_ORACLE_KJFS_EVENTS",
        "PSPRECOMP_ORACLE_EVENTS_ONLY",
    ):
        environment.pop(name, None)
    environment.update(
        {
            "PSPRECOMP_ORACLE_DIR": str(output),
            "PSPRECOMP_ORACLE_START_PC": f"{config.module['entry']:08x}",
            "PSPRECOMP_ORACLE_STEPS": str(config.trace_steps),
            "PSPRECOMP_ORACLE_TARGET": config.module["name"],
            "PSPRECOMP_ORACLE_MEMSTICK": str(memstick),
            "PSPRECOMP_ORACLE_RTC_EPOCH": str(
                config.settings["rtc_epoch_seconds"]
            ),
        }
    )
    command = [
        executable,
        "-i",
        "--graphics=software",
        "--timeout=300",
        iso,
    ]
    _run(command, cwd=checkout, env=environment)

    missing = [name for name in CAPTURE_FILES if not (output / name).is_file()]
    if missing:
        raise OracleError(
            "capture did not produce required files: " + ", ".join(missing)
        )
    done = (output / "trace.done").read_text(encoding="ascii").strip()
    if done != str(config.trace_steps):
        raise OracleError(
            f"trace completion marker {done!r} != {config.trace_steps}"
        )
    boot_state = _load_json(output / "boot_state.json")
    if boot_state.get("entry_pc") != config.module["entry"]:
        raise OracleError("captured entry PC does not match title config")
    manifest = {
        "schema": 1,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "identity": {
            "disc_id": config.disc["id"],
            "disc_version": config.disc["version"],
            "iso_size": config.disc["iso_size"],
            "iso_sha1": iso_sha1,
            "module_path": config.module["file"],
            "module_sha1": config.disc["files"][config.module["file"]],
            "module_entry": config.module["entry"],
            "ppsspp": build_identity,
            "trace_format": config.trace_format,
            "trace_steps": config.trace_steps,
            "settings": config.settings,
        },
        "files": {
            name: {
                "size": (output / name).stat().st_size,
                "sha256": hash_file(output / name),
            }
            for name in CAPTURE_FILES
        },
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "capture.complete").write_text(
        hash_file(manifest_path) + "\n",
        encoding="ascii",
    )
    print(f"capture complete: {output}")


def _load_tracediff():
    path = ROOT / "external" / "psp-recomp" / "tools" / "tracediff.py"
    spec = importlib.util.spec_from_file_location("mgspo_tracediff", path)
    if spec is None or spec.loader is None:
        raise OracleError(f"cannot load trace comparator {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _trace_context(tracediff, path, step, radius=2):
    lines = []
    start = max(0, step - radius)
    finish = step + radius
    for logical, parsed in enumerate(tracediff.iter_steps(str(path))):
        if logical > finish:
            break
        if logical >= start:
            index, pc, op, writes = parsed
            suffix = tracediff.describe_writes(writes)
            lines.append(
                f"{index} pc={pc} op={op}"
                + (f" {suffix}" if suffix else "")
            )
    return "\n".join(lines)


def _standalone_ops_equivalent(tracediff, first, second):
    if first == second or tracediff.is_syscall(first) or tracediff.is_syscall(second):
        return True
    first_word = int(first, 16)
    second_word = int(second, 16)
    return (
        first_word == 0x03E00008 and second_word >> 26 == 2
    ) or (
        second_word == 0x03E00008 and first_word >> 26 == 2
    )


def _diff_standalone_traces(tracediff, first, second):
    first_steps = iter(tracediff.iter_steps(str(first)))
    second_steps = iter(tracediff.iter_steps(str(second)))
    sentinel = object()
    logical_step = 0
    last_pc = "0x????????"
    while True:
        first_step = next(first_steps, sentinel)
        second_step = next(second_steps, sentinel)
        if first_step is sentinel or second_step is sentinel:
            if first_step is sentinel and second_step is sentinel:
                return None
            shorter = first if first_step is sentinel else second
            return (
                logical_step,
                last_pc,
                f"trace length differs ({shorter} ends first)",
            )
        first_index, first_pc, first_op, first_writes = first_step
        second_index, second_pc, second_op, second_writes = second_step
        last_pc = first_pc
        if first_index != second_index:
            return (
                logical_step,
                first_pc,
                f"step index {first_index} vs {second_index}",
            )
        if first_pc != second_pc:
            return (
                logical_step,
                first_pc,
                f"pc {first_pc} vs {second_pc}",
            )
        if not _standalone_ops_equivalent(
            tracediff, first_op, second_op
        ):
            return (
                logical_step,
                first_pc,
                f"op {first_op} vs {second_op}",
            )
        if first_writes != second_writes:
            only_first = {
                key: value
                for key, value in first_writes.items()
                if second_writes.get(key) != value
            }
            only_second = {
                key: value
                for key, value in second_writes.items()
                if first_writes.get(key) != value
            }
            detail = (
                "writes differ: "
                f"A[{tracediff.describe_writes(only_first)}] "
                f"B[{tracediff.describe_writes(only_second)}]"
            )
            return logical_step, first_pc, detail
        logical_step += 1


def compare_captures(first, second):
    first = first.resolve()
    second = second.resolve()
    first_manifest = verify_capture(first)
    second_manifest = verify_capture(second)
    if first_manifest.get("identity") != second_manifest.get("identity"):
        raise OracleError("capture identity manifests differ")

    for name in ("boot_state.json", "events.jsonl", "stack.bin"):
        first_path = first / name
        second_path = second / name
        if not first_path.is_file() or not second_path.is_file():
            raise OracleError(f"capture is missing {name}")
        if first_path.read_bytes() != second_path.read_bytes():
            raise OracleError(f"capture payload differs: {name}")

    tracediff = _load_tracediff()
    try:
        result = tracediff.diff(
            str(first / "cpu.trace"),
            str(second / "cpu.trace"),
        )
    except (OSError, tracediff.TraceError) as error:
        raise OracleError(f"cannot compare CPU traces: {error}") from error
    if result is not None:
        step, pc, detail = result
        first_context = _trace_context(
            tracediff,
            first / "cpu.trace",
            step,
        )
        second_context = _trace_context(
            tracediff,
            second / "cpu.trace",
            step,
        )
        raise OracleError(
            f"CPU trace divergence at step {step}, PC {pc}: {detail}\n"
            f"first:\n{first_context}\nsecond:\n{second_context}"
        )
    try:
        count = sum(1 for _ in tracediff.iter_steps(str(first / "cpu.trace")))
        second_count = sum(
            1 for _ in tracediff.iter_steps(str(second / "cpu.trace"))
        )
    except (OSError, tracediff.TraceError) as error:
        raise OracleError(f"cannot count CPU trace steps: {error}") from error
    expected_steps = first_manifest["identity"]["trace_steps"]
    if count != expected_steps or second_count != expected_steps:
        raise OracleError(
            f"capture traces contain {count} and {second_count} steps; "
            f"expected {expected_steps}"
        )
    print(
        f"OK: boot state, events, stack, and {count} CPU steps match"
    )


def compare_cpu_traces(reference, candidate, expected_steps):
    reference = reference.resolve()
    candidate = candidate.resolve()
    if not reference.is_file():
        raise OracleError(f"reference CPU trace does not exist: {reference}")
    if not candidate.is_file():
        raise OracleError(f"candidate CPU trace does not exist: {candidate}")
    completion = Path(str(candidate) + ".done")
    if not completion.is_file():
        raise OracleError(
            f"candidate trace completion marker does not exist: {completion}"
        )
    try:
        completed_steps = int(completion.read_text(encoding="ascii").strip())
    except ValueError as error:
        raise OracleError(
            f"invalid candidate trace completion marker: {completion}"
        ) from error
    if completed_steps != expected_steps:
        raise OracleError(
            f"candidate completion marker reports {completed_steps} steps; "
            f"expected {expected_steps}"
        )

    tracediff = _load_tracediff()
    try:
        result = _diff_standalone_traces(
            tracediff, reference, candidate
        )
        reference_steps = sum(
            1 for _ in tracediff.iter_steps(str(reference))
        )
        candidate_steps = sum(
            1 for _ in tracediff.iter_steps(str(candidate))
        )
    except (OSError, tracediff.TraceError) as error:
        raise OracleError(f"cannot compare CPU traces: {error}") from error
    if result is not None:
        step, pc, detail = result
        reference_context = _trace_context(
            tracediff,
            reference,
            step,
        )
        candidate_context = _trace_context(
            tracediff,
            candidate,
            step,
        )
        raise OracleError(
            f"CPU trace divergence at step {step}, PC {pc}: {detail}\n"
            f"reference:\n{reference_context}\n"
            f"candidate:\n{candidate_context}"
        )
    if reference_steps != expected_steps:
        raise OracleError(
            f"reference trace has {reference_steps} steps; "
            f"expected {expected_steps}"
        )
    if candidate_steps != expected_steps:
        raise OracleError(
            f"candidate trace has {candidate_steps} steps; "
            f"expected {expected_steps}"
        )
    print(f"OK: {candidate_steps} standalone CPU steps match the oracle")


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("verify-config")

    prepare = commands.add_parser("prepare")
    prepare.add_argument("--checkout", type=Path, default=DEFAULT_CHECKOUT)

    build = commands.add_parser("build")
    build.add_argument("--checkout", type=Path, default=DEFAULT_CHECKOUT)
    build.add_argument("--build-dir", type=Path, default=DEFAULT_BUILD)

    capture = commands.add_parser("capture")
    capture.add_argument("iso", type=Path)
    capture.add_argument("output", type=Path)
    capture.add_argument("--checkout", type=Path, default=DEFAULT_CHECKOUT)
    capture.add_argument("--build-dir", type=Path, default=DEFAULT_BUILD)

    compare = commands.add_parser("compare")
    compare.add_argument("first", type=Path)
    compare.add_argument("second", type=Path)
    compare_trace = commands.add_parser("compare-trace")
    compare_trace.add_argument("reference", type=Path)
    compare_trace.add_argument("candidate", type=Path)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "verify-config":
            print(
                f"PPSSPP oracle config ok: {config.version} "
                f"{config.commit}, {config.trace_steps} steps"
            )
        elif args.command == "prepare":
            prepare_checkout(config, args.checkout)
        elif args.command == "build":
            build_headless(config, args.checkout, args.build_dir)
        elif args.command == "capture":
            capture_oracle(
                config,
                args.checkout,
                args.build_dir,
                args.iso,
                args.output,
            )
        elif args.command == "compare":
            compare_captures(args.first, args.second)
        elif args.command == "compare-trace":
            compare_cpu_traces(
                args.reference,
                args.candidate,
                config.trace_steps,
            )
        return 0
    except (
        KeyError,
        OSError,
        OracleError,
        subprocess.SubprocessError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

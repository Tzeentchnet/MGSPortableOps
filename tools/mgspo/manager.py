#!/usr/bin/env python3
"""GUI manager for verifying, building, installing, configuring, and launching MGSPO."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import tomllib
from typing import Callable, Iterable


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "mgspo.toml"
STATE_PATH = ROOT / "build" / "mgspo" / "manager.json"

BUILD_CONFIGS = {
    "d3d12": {
        "label": "Experimental D3D12",
        "configure_preset": "clang-cl-d3d12-experimental",
        "build_preset": "mgspo-d3d12-experimental",
        "build_dir": ROOT / "out" / "build" / "clang-cl-d3d12-experimental",
        "default_install": ROOT / "out" / "install" / "MGSPortableOps-d3d12",
    },
    "software": {
        "label": "Software reference",
        "configure_preset": "clang-cl",
        "build_preset": "mgspo-runtime",
        "build_dir": ROOT / "out" / "build" / "clang-cl",
        "default_install": ROOT / "out" / "install" / "MGSPortableOps-software",
    },
}


class ManagerError(RuntimeError):
    """A user-actionable manager failure."""


class ManagerCancelled(ManagerError):
    """The user cancelled an active operation."""


@dataclass
class ManagerState:
    iso_path: str = ""
    install_path: str = str(BUILD_CONFIGS["d3d12"]["default_install"])
    build: str = "d3d12"

    def validate(self, require_iso: bool = False) -> None:
        if self.build not in BUILD_CONFIGS:
            raise ManagerError(f"unknown build type: {self.build}")
        if not self.install_path:
            raise ManagerError("select an install directory")
        install = Path(self.install_path).expanduser().resolve()
        if install == ROOT.resolve() or install == Path(install.anchor):
            raise ManagerError(
                "the install directory cannot be the repository or a drive root"
            )
        if require_iso:
            if not self.iso_path:
                raise ManagerError("select the supported Portable Ops ISO")
            iso = Path(self.iso_path).expanduser()
            if not iso.is_file():
                raise ManagerError(f"ISO not found: {iso}")


@dataclass
class GraphicsSettings:
    renderer: str = "d3d12"
    internal_resolution: int = 2
    texture_scale: int = 1
    d3d12_full_rate: bool = False
    anti_aliasing: str = "off"
    skip_startup: bool = False

    def validate(self, build: str | None = None) -> None:
        if self.renderer not in {"auto", "d3d12", "sw"}:
            raise ManagerError(f"unsupported renderer: {self.renderer}")
        if not 1 <= self.internal_resolution <= 8:
            raise ManagerError("internal resolution must be between 1x and 8x")
        if not 1 <= self.texture_scale <= 5:
            raise ManagerError("texture scale must be between 1x and 5x")
        if self.anti_aliasing not in {"off", "smaa"}:
            raise ManagerError(
                f"unsupported anti-aliasing mode: {self.anti_aliasing}"
            )
        if self.anti_aliasing == "smaa" and self.renderer == "sw":
            raise ManagerError("SMAA requires the D3D12 renderer")
        if build == "software" and self.renderer == "d3d12":
            raise ManagerError(
                "the software build does not contain the D3D12 renderer"
            )

    def to_text(self) -> str:
        self.validate()
        return (
            "# PSP recomp graphics config v4\n"
            f"renderer = {self.renderer}\n"
            f"internal_resolution = {self.internal_resolution}\n"
            f"texture_scale = {self.texture_scale}\n"
            f"d3d12_full_rate = {int(self.d3d12_full_rate)}\n"
            f"anti_aliasing = {self.anti_aliasing}\n"
            f"skip_startup = {'on' if self.skip_startup else 'off'}\n"
        )


@dataclass(frozen=True)
class DependencyCheck:
    name: str
    ok: bool
    detail: str


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise


def load_state(path: Path = STATE_PATH) -> ManagerState:
    if not path.exists():
        return ManagerState()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ManagerError(f"cannot read manager state {path}: {error}") from error
    if not isinstance(value, dict):
        raise ManagerError(f"manager state must be a JSON object: {path}")
    expected = {"iso_path", "install_path", "build"}
    unknown = set(value) - expected
    if unknown:
        raise ManagerError(
            f"manager state has unknown fields: {', '.join(sorted(unknown))}"
        )
    if any(not isinstance(value.get(key, ""), str) for key in expected):
        raise ManagerError(f"manager state fields must be strings: {path}")
    state = ManagerState(
        iso_path=value.get("iso_path", ""),
        install_path=value.get(
            "install_path",
            str(BUILD_CONFIGS["d3d12"]["default_install"]),
        ),
        build=value.get("build", "d3d12"),
    )
    state.validate()
    return state


def save_state(state: ManagerState, path: Path = STATE_PATH) -> None:
    state.validate()
    atomic_write_text(path, json.dumps(asdict(state), indent=2) + "\n")


def parse_graphics_text(text: str) -> GraphicsSettings:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        name, separator, value = line.partition("=")
        if not separator or not name.strip() or not value.strip():
            raise ManagerError(
                f"invalid graphics setting on line {line_number}"
            )
        name = name.strip()
        if name in values:
            raise ManagerError(
                f"duplicate graphics setting on line {line_number}: {name}"
            )
        values[name] = value.strip().lower()
    expected = {
        "renderer",
        "internal_resolution",
        "texture_scale",
        "d3d12_full_rate",
        "anti_aliasing",
        "skip_startup",
    }
    unknown = set(values) - expected
    if unknown:
        raise ManagerError(
            f"unknown graphics settings: {', '.join(sorted(unknown))}"
        )

    defaults = GraphicsSettings()

    def integer(name: str, default: int) -> int:
        try:
            return int(values.get(name, str(default)), 10)
        except ValueError as error:
            raise ManagerError(f"{name} must be an integer") from error

    def toggle(name: str, default: bool) -> bool:
        value = values.get(name, "on" if default else "off")
        if value in {"1", "on", "true"}:
            return True
        if value in {"0", "off", "false"}:
            return False
        raise ManagerError(f"{name} must be on or off")

    settings = GraphicsSettings(
        renderer=values.get("renderer", defaults.renderer),
        internal_resolution=integer(
            "internal_resolution", defaults.internal_resolution
        ),
        texture_scale=integer("texture_scale", defaults.texture_scale),
        d3d12_full_rate=toggle(
            "d3d12_full_rate", defaults.d3d12_full_rate
        ),
        anti_aliasing=values.get(
            "anti_aliasing", defaults.anti_aliasing
        ),
        skip_startup=toggle("skip_startup", defaults.skip_startup),
    )
    settings.validate()
    return settings


def load_graphics_settings(install_path: Path) -> GraphicsSettings:
    path = install_path / "graphics.ini"
    if not path.exists():
        return GraphicsSettings()
    try:
        return parse_graphics_text(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as error:
        raise ManagerError(f"cannot read {path}: {error}") from error


def save_graphics_settings(
    install_path: Path,
    settings: GraphicsSettings,
    build: str | None = None,
) -> Path:
    settings.validate(build)
    path = install_path / "graphics.ini"
    try:
        atomic_write_text(path, settings.to_text())
    except OSError as error:
        raise ManagerError(f"cannot save {path}: {error}") from error
    return path


def disc_identity(config_path: Path = CONFIG_PATH) -> tuple[int, str]:
    try:
        with config_path.open("rb") as stream:
            config = tomllib.load(stream)
        return int(config["disc"]["iso_size"]), str(config["disc"]["iso_sha1"])
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        tomllib.TOMLDecodeError,
    ) as error:
        raise ManagerError(
            f"cannot read disc identity from {config_path}: {error}"
        ) from error


def hash_file(path: Path, cancel: threading.Event | None = None) -> str:
    digest = hashlib.sha1()
    try:
        with path.open("rb") as stream:
            while True:
                if cancel and cancel.is_set():
                    raise ManagerCancelled("operation cancelled")
                block = stream.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
    except OSError as error:
        raise ManagerError(f"cannot read {path}: {error}") from error
    return digest.hexdigest()


def verify_iso(
    iso_path: Path,
    log: Callable[[str], None] = print,
    cancel: threading.Event | None = None,
) -> str:
    expected_size, expected_sha1 = disc_identity()
    try:
        actual_size = iso_path.stat().st_size
    except OSError as error:
        raise ManagerError(f"cannot inspect ISO {iso_path}: {error}") from error
    if actual_size != expected_size:
        raise ManagerError(
            f"ISO size {actual_size:,} does not match the supported "
            f"{expected_size:,}-byte image"
        )
    log(f"Hashing {iso_path} ({actual_size:,} bytes)...")
    actual_sha1 = hash_file(iso_path, cancel)
    if actual_sha1.lower() != expected_sha1.lower():
        raise ManagerError(
            f"ISO SHA-1 {actual_sha1} does not match supported "
            f"{expected_sha1}"
        )
    log(f"Supported ISO verified ({actual_sha1}).")
    return actual_sha1


def visual_studio_environment() -> dict[str, str]:
    if os.name != "nt":
        raise ManagerError("the Portable Ops runtime currently builds on Windows")
    program_files = os.environ.get("ProgramFiles(x86)")
    if not program_files:
        raise ManagerError("ProgramFiles(x86) is not set")
    vswhere = (
        Path(program_files)
        / "Microsoft Visual Studio"
        / "Installer"
        / "vswhere.exe"
    )
    if not vswhere.is_file():
        raise ManagerError(
            "Visual Studio Installer was not found; install Visual Studio "
            "2022 Build Tools with the Desktop development with C++ workload"
        )
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
        raise ManagerError(
            "Visual Studio 2022 C++ tools were not found; install the "
            "Desktop development with C++ workload and clang-cl"
        )
    developer = Path(installation) / "Common7" / "Tools" / "VsDevCmd.bat"
    with tempfile.TemporaryDirectory(prefix="mgspo-manager-vsenv-") as directory:
        script = Path(directory) / "environment.cmd"
        script.write_text(
            "@echo off\n"
            f'call "{developer}" -arch=x64 -host_arch=x64 >nul\n'
            "if errorlevel 1 exit /b %errorlevel%\n"
            "set\n",
            encoding="ascii",
        )
        result = subprocess.run(
            [os.environ.get("ComSpec", "cmd.exe"), "/d", "/c", str(script)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    if result.returncode:
        detail = (result.stdout + result.stderr).strip()
        raise ManagerError(
            "Visual Studio developer environment failed"
            + (f": {detail}" if detail else "")
        )
    environment: dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            environment[key] = value
    path_key = next(
        (key for key in environment if key.lower() == "path"), "Path"
    )
    environment[path_key] = os.pathsep.join(
        entry
        for entry in environment.get(path_key, "").split(os.pathsep)
        if "winlibs" not in entry.lower()
    )
    return environment


def diagnose() -> tuple[list[DependencyCheck], dict[str, str] | None]:
    checks = [
        DependencyCheck(
            "Python",
            sys.version_info >= (3, 11),
            sys.version.split()[0],
        ),
        DependencyCheck(
            "Repository",
            (ROOT / "CMakeLists.txt").is_file(),
            str(ROOT),
        ),
    ]
    environment: dict[str, str] | None = None
    try:
        environment = visual_studio_environment()
        checks.append(
            DependencyCheck(
                "Visual Studio C++ environment",
                True,
                environment.get("VisualStudioVersion", "available"),
            )
        )
    except ManagerError as error:
        checks.append(
            DependencyCheck(
                "Visual Studio C++ environment", False, str(error)
            )
        )
    search_path = (
        next(
            (
                value
                for key, value in environment.items()
                if key.lower() == "path"
            ),
            "",
        )
        if environment
        else os.environ.get("PATH", "")
    )
    for name in ("git", "cmake", "ninja", "clang-cl"):
        executable = shutil.which(name, path=search_path)
        checks.append(
            DependencyCheck(
                name,
                executable is not None,
                executable or "not found",
            )
        )
    submodule = (
        ROOT / "external" / "psp-recomp" / "src" / "rt" / "recomp.h"
    )
    checks.append(
        DependencyCheck(
            "psp-recomp submodule",
            True,
            str(submodule)
            if submodule.is_file()
            else "not initialized; Build & Install will initialize it",
        )
    )
    return checks, environment


def workflow_commands(state: ManagerState) -> list[list[str]]:
    state.validate(require_iso=True)
    build = BUILD_CONFIGS[state.build]
    return [
        ["git", "submodule", "update", "--init", "--recursive"],
        [
            sys.executable,
            str(ROOT / "tools" / "mgspo" / "extract.py"),
            str(Path(state.iso_path).expanduser().resolve()),
        ],
        [sys.executable, str(ROOT / "tools" / "mgspo" / "gen.py")],
        ["cmake", "--preset", str(build["configure_preset"])],
        ["cmake", "--build", "--preset", str(build["build_preset"])],
        [
            "cmake",
            "--install",
            str(build["build_dir"]),
            "--prefix",
            str(Path(state.install_path).expanduser().resolve()),
        ],
    ]


def run_command(
    command: list[str],
    environment: dict[str, str],
    log: Callable[[str], None],
    cancel: threading.Event,
    on_process: Callable[[subprocess.Popen[str] | None], None] | None = None,
) -> None:
    if cancel.is_set():
        raise ManagerCancelled("operation cancelled")
    log(f"> {subprocess.list2cmdline(command)}")
    try:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except OSError as error:
        raise ManagerError(f"cannot start {command[0]}: {error}") from error
    if on_process:
        on_process(process)
    output: queue.Queue[str | None] = queue.Queue()

    def read_output() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            output.put(line.rstrip())
        output.put(None)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    finished_output = False
    try:
        while process.poll() is None or not finished_output:
            if cancel.is_set() and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                raise ManagerCancelled("operation cancelled")
            try:
                line = output.get(timeout=0.1)
            except queue.Empty:
                continue
            if line is None:
                finished_output = True
            elif line:
                log(line)
    finally:
        reader.join(timeout=1)
        if on_process:
            on_process(None)
    if process.returncode:
        raise ManagerError(
            f"{command[0]} failed with exit code {process.returncode}"
        )


def build_and_install(
    state: ManagerState,
    log: Callable[[str], None] = print,
    cancel: threading.Event | None = None,
    on_process: Callable[[subprocess.Popen[str] | None], None] | None = None,
) -> Path:
    state.validate(require_iso=True)
    cancel = cancel or threading.Event()
    verify_iso(Path(state.iso_path).expanduser().resolve(), log, cancel)
    checks, environment = diagnose()
    failures = [check for check in checks if not check.ok]
    if failures or environment is None:
        detail = "; ".join(
            f"{check.name}: {check.detail}" for check in failures
        )
        raise ManagerError(f"requirements are not ready: {detail}")
    save_state(state)
    for command in workflow_commands(state):
        run_command(
            command, environment, log, cancel, on_process=on_process
        )
    executable = (
        Path(state.install_path).expanduser().resolve()
        / "MGSPortableOps.exe"
    )
    if not executable.is_file():
        raise ManagerError(
            f"install completed without the expected executable: {executable}"
        )
    log(f"Installed to {executable.parent}.")
    return executable


def launch_runtime(
    state: ManagerState,
    option: str | None = None,
) -> subprocess.Popen[bytes]:
    state.validate(require_iso=True)
    executable = (
        Path(state.install_path).expanduser().resolve()
        / "MGSPortableOps.exe"
    )
    if not executable.is_file():
        raise ManagerError(
            f"runtime is not installed: {executable}; select Build & Install first"
        )
    command = [str(executable)]
    if option:
        command.append(option)
    environment = os.environ.copy()
    environment["PSP_ISO"] = str(Path(state.iso_path).expanduser().resolve())
    try:
        return subprocess.Popen(
            command,
            cwd=executable.parent,
            env=environment,
            creationflags=(
                subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            ),
        )
    except OSError as error:
        raise ManagerError(f"cannot launch {executable}: {error}") from error


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnose", action="store_true")
    parser.add_argument("--build-install", action="store_true")
    parser.add_argument("--launch", action="store_true")
    parser.add_argument("--configure", action="store_true")
    parser.add_argument("--iso", type=Path)
    parser.add_argument("--install-dir", type=Path)
    parser.add_argument("--build", choices=sorted(BUILD_CONFIGS))
    return parser.parse_args(argv[1:])


def state_from_args(
    arguments: argparse.Namespace,
    state: ManagerState,
) -> ManagerState:
    if arguments.iso is not None:
        state.iso_path = str(arguments.iso.expanduser().resolve())
    if arguments.install_dir is not None:
        state.install_path = str(
            arguments.install_dir.expanduser().resolve()
        )
    if arguments.build is not None:
        old_default = str(BUILD_CONFIGS[state.build]["default_install"])
        state.build = arguments.build
        if state.install_path == old_default:
            state.install_path = str(
                BUILD_CONFIGS[state.build]["default_install"]
            )
    state.validate()
    return state


def launch_gui(initial_state: ManagerState) -> int:
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except ImportError as error:
        raise ManagerError(
            "Tkinter is unavailable; install the standard Windows Python "
            "distribution with Tcl/Tk support"
        ) from error

    class ManagerWindow:
        def __init__(self, root: tk.Tk, state: ManagerState) -> None:
            self.root = root
            self.root.title("Metal Gear Solid: Portable Ops Manager")
            self.root.minsize(790, 610)
            self.events: queue.Queue[tuple[str, object]] = queue.Queue()
            self.cancel = threading.Event()
            self.process: subprocess.Popen[str] | None = None
            self.busy = False

            self.iso = tk.StringVar(value=state.iso_path)
            self.install = tk.StringVar(value=state.install_path)
            self.build_label = tk.StringVar(
                value=str(BUILD_CONFIGS[state.build]["label"])
            )
            self.status = tk.StringVar(value="Ready")

            self.renderer = tk.StringVar(value="d3d12")
            self.resolution = tk.IntVar(value=2)
            self.texture_scale = tk.IntVar(value=1)
            self.full_rate = tk.BooleanVar(value=False)
            self.anti_aliasing = tk.StringVar(value="off")
            self.skip_startup = tk.BooleanVar(value=False)

            notebook = ttk.Notebook(root)
            notebook.pack(fill="both", expand=True, padx=10, pady=10)
            install_tab = ttk.Frame(notebook, padding=12)
            graphics_tab = ttk.Frame(notebook, padding=12)
            notebook.add(install_tab, text="Install and Launch")
            notebook.add(graphics_tab, text="Graphics")
            self._create_install_tab(install_tab, ttk, tk, filedialog)
            self._create_graphics_tab(graphics_tab, ttk)
            self.progress = ttk.Progressbar(
                root, mode="indeterminate", length=300
            )
            self.progress.pack(fill="x", padx=12)
            ttk.Label(root, textvariable=self.status).pack(
                fill="x", padx=12, pady=(4, 10)
            )
            self.messagebox = messagebox
            self.filedialog = filedialog
            self.root.protocol("WM_DELETE_WINDOW", self.close)
            self.root.after(100, self._drain_events)
            self._load_graphics(silent=True)

        def _create_install_tab(
            self, tab, ttk_module, tk_module, filedialog_module
        ) -> None:
            tab.columnconfigure(1, weight=1)
            ttk_module.Label(tab, text="Supported USA ISO:").grid(
                row=0, column=0, sticky="w", pady=4
            )
            ttk_module.Entry(tab, textvariable=self.iso).grid(
                row=0, column=1, sticky="ew", padx=8
            )
            self.browse_iso_button = ttk_module.Button(
                tab, text="Browse...", command=self.browse_iso
            )
            self.browse_iso_button.grid(row=0, column=2)

            ttk_module.Label(tab, text="Runtime build:").grid(
                row=1, column=0, sticky="w", pady=4
            )
            self.build_combo = ttk_module.Combobox(
                tab,
                textvariable=self.build_label,
                state="readonly",
                values=[
                    BUILD_CONFIGS["d3d12"]["label"],
                    BUILD_CONFIGS["software"]["label"],
                ],
            )
            self.build_combo.grid(
                row=1, column=1, sticky="w", padx=8, pady=4
            )
            self.build_combo.bind(
                "<<ComboboxSelected>>", self._build_changed
            )

            ttk_module.Label(tab, text="Install directory:").grid(
                row=2, column=0, sticky="w", pady=4
            )
            ttk_module.Entry(tab, textvariable=self.install).grid(
                row=2, column=1, sticky="ew", padx=8
            )
            self.browse_install_button = ttk_module.Button(
                tab, text="Browse...", command=self.browse_install
            )
            self.browse_install_button.grid(row=2, column=2)

            button_frame = ttk_module.Frame(tab)
            button_frame.grid(
                row=3, column=0, columnspan=3, sticky="ew", pady=(12, 8)
            )
            self.check_button = ttk_module.Button(
                button_frame,
                text="Check Requirements",
                command=self.check_requirements,
            )
            self.check_button.pack(side="left", padx=(0, 6))
            self.build_button = ttk_module.Button(
                button_frame,
                text="Build & Install",
                command=self.build_install,
            )
            self.build_button.pack(side="left", padx=6)
            self.launch_button = ttk_module.Button(
                button_frame, text="Launch Game", command=self.launch
            )
            self.launch_button.pack(side="left", padx=6)
            self.controls_button = ttk_module.Button(
                button_frame,
                text="Configure Controls",
                command=self.configure_controls,
            )
            self.controls_button.pack(side="left", padx=6)
            self.cancel_button = ttk_module.Button(
                button_frame,
                text="Cancel",
                command=self.cancel_operation,
                state="disabled",
            )
            self.cancel_button.pack(side="right")

            self.log = tk_module.Text(
                tab, height=22, wrap="word", state="disabled"
            )
            self.log.grid(
                row=4,
                column=0,
                columnspan=3,
                sticky="nsew",
                pady=(4, 0),
            )
            tab.rowconfigure(4, weight=1)

        def _create_graphics_tab(self, tab, ttk_module) -> None:
            tab.columnconfigure(1, weight=1)
            rows = [
                ("Renderer:", self.renderer, ("auto", "d3d12", "sw")),
                (
                    "Internal resolution:",
                    self.resolution,
                    tuple(range(1, 9)),
                ),
                (
                    "Texture upscaling:",
                    self.texture_scale,
                    tuple(range(1, 6)),
                ),
                (
                    "Anti-aliasing:",
                    self.anti_aliasing,
                    ("off", "smaa"),
                ),
            ]
            for row, (label, variable, values) in enumerate(rows):
                ttk_module.Label(tab, text=label).grid(
                    row=row, column=0, sticky="w", pady=7
                )
                ttk_module.Combobox(
                    tab,
                    textvariable=variable,
                    values=values,
                    state="readonly",
                    width=24,
                ).grid(row=row, column=1, sticky="w", padx=10)
            ttk_module.Checkbutton(
                tab,
                text="Use full-rate D3D12 shading",
                variable=self.full_rate,
            ).grid(row=4, column=0, columnspan=2, sticky="w", pady=7)
            ttk_module.Checkbutton(
                tab,
                text="Skip the startup sequence after normal initialization",
                variable=self.skip_startup,
            ).grid(row=5, column=0, columnspan=2, sticky="w", pady=7)
            ttk_module.Label(
                tab,
                text=(
                    "These settings are written beside the installed executable. "
                    "Renderer, resolution, texture scaling, shading, and anti-aliasing "
                    "apply on the next launch. Press F1 in game for the runtime menu."
                ),
                wraplength=650,
            ).grid(
                row=6, column=0, columnspan=2, sticky="w", pady=(16, 10)
            )
            frame = ttk_module.Frame(tab)
            frame.grid(row=7, column=0, columnspan=2, sticky="w")
            ttk_module.Button(
                frame,
                text="Save Graphics Settings",
                command=self.save_graphics,
            ).pack(side="left", padx=(0, 8))
            ttk_module.Button(
                frame,
                text="Open Native Settings",
                command=self.configure_all,
            ).pack(side="left")

        def current_state(self, require_iso: bool = False) -> ManagerState:
            label_to_key = {
                str(value["label"]): key
                for key, value in BUILD_CONFIGS.items()
            }
            state = ManagerState(
                iso_path=self.iso.get().strip(),
                install_path=self.install.get().strip(),
                build=label_to_key.get(
                    self.build_label.get(), "d3d12"
                ),
            )
            state.validate(require_iso=require_iso)
            return state

        def browse_iso(self) -> None:
            path = self.filedialog.askopenfilename(
                title="Select supported Portable Ops ISO",
                filetypes=[("Disc images", "*.iso *.ISO"), ("All files", "*.*")],
            )
            if path:
                self.iso.set(path)

        def browse_install(self) -> None:
            path = self.filedialog.askdirectory(
                title="Select install directory",
                initialdir=self.install.get() or str(ROOT),
            )
            if path:
                self.install.set(path)
                self._load_graphics(silent=True)

        def _build_changed(self, _event=None) -> None:
            current = Path(self.install.get()).resolve()
            defaults = {
                Path(value["default_install"]).resolve()
                for value in BUILD_CONFIGS.values()
            }
            if current in defaults:
                state = self.current_state()
                self.install.set(
                    str(BUILD_CONFIGS[state.build]["default_install"])
                )
            if self.current_state().build == "software":
                self.renderer.set("sw")
                self.anti_aliasing.set("off")

        def log_line(self, text: str) -> None:
            self.log.configure(state="normal")
            self.log.insert("end", text + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")

        def _set_busy(self, busy: bool, status: str) -> None:
            self.busy = busy
            self.status.set(status)
            state = "disabled" if busy else "normal"
            for button in (
                self.browse_iso_button,
                self.browse_install_button,
                self.check_button,
                self.build_button,
                self.launch_button,
                self.controls_button,
            ):
                button.configure(state=state)
            self.build_combo.configure(
                state="disabled" if busy else "readonly"
            )
            self.cancel_button.configure(
                state="normal" if busy else "disabled"
            )
            if busy:
                self.progress.start(10)
            else:
                self.progress.stop()

        def _start_worker(
            self, status: str, operation: Callable[[], object]
        ) -> None:
            if self.busy:
                return
            self.cancel.clear()
            self._set_busy(True, status)

            def worker() -> None:
                try:
                    result = operation()
                    self.events.put(("done", result))
                except ManagerCancelled as error:
                    self.events.put(("cancelled", str(error)))
                except Exception as error:
                    self.events.put(("error", str(error)))

            threading.Thread(target=worker, daemon=True).start()

        def _drain_events(self) -> None:
            try:
                while True:
                    kind, value = self.events.get_nowait()
                    if kind == "log":
                        self.log_line(str(value))
                    elif kind == "process":
                        self.process = value  # type: ignore[assignment]
                    elif kind == "done":
                        self._set_busy(False, "Ready")
                        if value:
                            self.log_line(str(value))
                    elif kind == "cancelled":
                        self._set_busy(False, "Cancelled")
                        self.log_line(str(value))
                    elif kind == "error":
                        self._set_busy(False, "Failed")
                        self.log_line(f"ERROR: {value}")
                        self.messagebox.showerror(
                            "Portable Ops Manager", str(value)
                        )
            except queue.Empty:
                pass
            self.root.after(100, self._drain_events)

        def check_requirements(self) -> None:
            def operation() -> str:
                checks, _environment = diagnose()
                for check in checks:
                    self.events.put(
                        (
                            "log",
                            f"{'OK' if check.ok else 'MISSING'}: "
                            f"{check.name}: {check.detail}",
                        )
                    )
                if any(not check.ok for check in checks):
                    raise ManagerError(
                        "one or more required tools are missing"
                    )
                return "All required build tools are available."

            self._start_worker("Checking requirements...", operation)

        def build_install(self) -> None:
            try:
                state = self.current_state(require_iso=True)
            except ManagerError as error:
                self.messagebox.showerror(
                    "Portable Ops Manager", str(error)
                )
                return

            def operation() -> str:
                executable = build_and_install(
                    state,
                    log=lambda line: self.events.put(("log", line)),
                    cancel=self.cancel,
                    on_process=lambda process: self.events.put(
                        ("process", process)
                    ),
                )
                return f"Build and install complete: {executable}"

            self._start_worker("Building and installing...", operation)

        def cancel_operation(self) -> None:
            if self.busy:
                self.cancel.set()
                self.status.set("Cancelling...")

        def launch(self) -> None:
            try:
                state = self.current_state(require_iso=True)
                save_state(state)
                launch_runtime(state)
                self.status.set("Game launched")
            except ManagerError as error:
                self.messagebox.showerror(
                    "Portable Ops Manager", str(error)
                )

        def configure_controls(self) -> None:
            try:
                state = self.current_state(require_iso=True)
                save_state(state)
                launch_runtime(state, "--configure-input")
            except ManagerError as error:
                self.messagebox.showerror(
                    "Portable Ops Manager", str(error)
                )

        def configure_all(self) -> None:
            try:
                state = self.current_state(require_iso=True)
                save_state(state)
                launch_runtime(state, "--configure")
            except ManagerError as error:
                self.messagebox.showerror(
                    "Portable Ops Manager", str(error)
                )

        def graphics_settings(self) -> GraphicsSettings:
            try:
                settings = GraphicsSettings(
                    renderer=self.renderer.get(),
                    internal_resolution=int(self.resolution.get()),
                    texture_scale=int(self.texture_scale.get()),
                    d3d12_full_rate=bool(self.full_rate.get()),
                    anti_aliasing=self.anti_aliasing.get(),
                    skip_startup=bool(self.skip_startup.get()),
                )
            except (TypeError, ValueError) as error:
                raise ManagerError(
                    "resolution and texture scale must be integers"
                ) from error
            settings.validate(self.current_state().build)
            return settings

        def _load_graphics(self, silent: bool = False) -> None:
            try:
                state = self.current_state()
                settings = load_graphics_settings(
                    Path(state.install_path).expanduser().resolve()
                )
                if (
                    state.build == "software"
                    and settings.renderer == "d3d12"
                ):
                    settings.renderer = "sw"
                    settings.anti_aliasing = "off"
                self.renderer.set(settings.renderer)
                self.resolution.set(settings.internal_resolution)
                self.texture_scale.set(settings.texture_scale)
                self.full_rate.set(settings.d3d12_full_rate)
                self.anti_aliasing.set(settings.anti_aliasing)
                self.skip_startup.set(settings.skip_startup)
            except ManagerError as error:
                if not silent:
                    self.messagebox.showerror(
                        "Portable Ops Manager", str(error)
                    )

        def save_graphics(self) -> None:
            try:
                state = self.current_state()
                path = save_graphics_settings(
                    Path(state.install_path).expanduser().resolve(),
                    self.graphics_settings(),
                    state.build,
                )
                save_state(state)
                self.status.set(f"Saved {path}")
            except ManagerError as error:
                self.messagebox.showerror(
                    "Portable Ops Manager", str(error)
                )

        def close(self) -> None:
            if self.busy:
                if not self.messagebox.askyesno(
                    "Portable Ops Manager",
                    "Cancel the active operation and close?",
                ):
                    return
                self.cancel.set()
            try:
                save_state(self.current_state())
            except ManagerError as error:
                if not self.messagebox.askyesno(
                    "Portable Ops Manager",
                    f"Settings could not be saved:\n{error}\n\nClose anyway?",
                ):
                    return
            self.root.destroy()

    root = tk.Tk()
    ManagerWindow(root, initial_state)
    root.mainloop()
    return 0


def main(argv: list[str]) -> int:
    arguments = parse_args(argv)
    try:
        state = state_from_args(arguments, load_state())
        if arguments.diagnose:
            checks, _environment = diagnose()
            for check in checks:
                print(
                    f"{'OK' if check.ok else 'MISSING'}: "
                    f"{check.name}: {check.detail}"
                )
            return 0 if all(check.ok for check in checks) else 1
        if arguments.build_install:
            build_and_install(state)
            return 0
        if arguments.launch or arguments.configure:
            save_state(state)
            launch_runtime(
                state, "--configure" if arguments.configure else None
            )
            return 0
        return launch_gui(state)
    except (ManagerError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

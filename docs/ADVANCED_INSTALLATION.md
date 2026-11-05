# Advanced installation

This guide covers the manual source-build workflow. Most users should
double-click `Setup.bat` in the repository root or run:

```powershell
python tools\mgspo\manager.py
```

The repository is source-only. You must provide the supported USA
ULUS-10202 v1.00 ISO; do not distribute the ISO, extracted files, generated
game code, or installed private image.

## Prerequisites

- Windows 10/11 x64
- Python 3.11 or newer
- Git
- CMake 3.25 or newer
- Ninja
- Visual Studio 2022 Build Tools with:
  - Desktop development with C++;
  - clang-cl; and
  - a Windows SDK

Run build commands from an x64 Visual Studio developer shell. The setup
manager can check the same environment without building:

```powershell
python tools\mgspo\manager.py --diagnose
```

## 1. Initialize the pinned runtime

```powershell
git submodule update --init --recursive
```

The pinned `external/psp-recomp` checkout must remain clean and match the
identity in `config/mgspo.toml`.

## 2. Verify and extract the disc

```powershell
python tools\mgspo\extract.py `
  "D:\Games\Metal Gear Solid - Portable Ops (USA).iso"
```

Extraction verifies the exact ISO size, SHA-1, and required file identities
before publishing output. Private extracted files remain under the ignored
`build/mgspo/disc` directory.

## 3. Generate native code

```powershell
python tools\mgspo\gen.py
```

Generation writes the relocated private image and 232 native translation
units under ignored build directories. It fails if the pinned toolkit,
module identities, accepted function set, or generated control flow differs
from the measured contract.

## 4. Configure and build

### Software reference runtime

```powershell
cmake --preset clang-cl
cmake --build --preset mgspo-runtime
```

Output:

```text
out\build\clang-cl\MGSPortableOps.exe
```

### Experimental D3D12 runtime

```powershell
cmake --preset clang-cl-d3d12-experimental
cmake --build --preset mgspo-d3d12-experimental
```

Output:

```text
out\build\clang-cl-d3d12-experimental\MGSPortableOps.exe
```

D3D12 remains experimental. See [STATUS.md](STATUS.md) for the current
correctness boundary.

### Trace-enabled runtime

```powershell
cmake --preset clang-cl-trace
cmake --build --preset mgspo-trace
```

Use the trace build only for bounded diagnostic and oracle workflows.

## 5. Stage a local installation

Software build:

```powershell
cmake --install out\build\clang-cl `
  --prefix out\install\MGSPortableOps-software
```

D3D12 build:

```powershell
cmake --install out\build\clang-cl-d3d12-experimental `
  --prefix out\install\MGSPortableOps-d3d12
```

The local installation contains:

- `MGSPortableOps.exe`;
- the private generated `mgspo_image.bin`;
- PSP font and VFPU runtime assets;
- the project README and license; and
- `SDL3.dll` for the D3D12 build.

It does not contain or copy the source ISO.

## 6. Configure and launch

Set the supported ISO for the current shell:

```powershell
$env:PSP_ISO = "D:\Games\Metal Gear Solid - Portable Ops (USA).iso"
```

Open all native settings without starting the guest:

```powershell
out\build\clang-cl\MGSPortableOps.exe --configure
```

Open only the input remapper:

```powershell
out\build\clang-cl\MGSPortableOps.exe --configure-input
```

Launch the software build:

```powershell
out\build\clang-cl\MGSPortableOps.exe
```

Press F1 during gameplay to pause guest execution and open the runtime
settings hub. Input changes apply immediately. Graphics changes require a
restart.

## 7. Optional validation

### Runtime contract

```powershell
out\build\clang-cl\MGSPortableOps.exe --verify-contract
```

This verifies the boot image, measured state, module identities and lifecycle,
native ZLIB policy, title HLE overrides, UMD block-device behavior, ATRAC
frame sizing, and validated VFPU operations.

### Plaintext service lifecycle

```powershell
python tools\mgspo\module_lifecycle.py `
  out\build\clang-cl\MGSPortableOps.exe `
  $env:PSP_ISO `
  --out build\mgspo\standalone\module-lifecycle
```

The probe checks exact ZLIB, SOUND2, and KJFS callback addresses, module-thread
state, KJFS worker creation, callback exit status, and reverse-order stopping.
Pass `--interpreted-zlib` to exercise interpreter fallback.

### First-mission smoke route

```powershell
python tools\mgspo\smoke.py `
  out\build\clang-cl\MGSPortableOps.exe `
  $env:PSP_ISO `
  --out build\mgspo\standalone\first-mission
```

The output directory must not already exist. The verifier uses PSP VBlank
pacing, creates an isolated clean profile, enters the first mission, and
requires the exact accepted `240x272` pause-region hash. It fails on route,
module, UMD, savedata, lifecycle, native-ZLIB, fatal-event, or framebuffer
identity drift.

For oracle captures, service comparisons, performance reports, and other
research workflows, continue with [REPRODUCTION.md](REPRODUCTION.md).

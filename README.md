# Metal Gear Solid: Portable Ops Recomp

Source-only Windows static recompilation work for **Metal Gear Solid:
Portable Ops (ULUS-10202 v1.00)** using
[`psp-recomp`](https://github.com/Tzeentchnet/psp-recomp).

No game executable, generated game C, disc data, save data, trace, or capture
belongs in this repository. Supply your own supported USA disc image.

> **Development build:** first-mission bring-up is working, but this is not yet
> a playable release. See [project status and next gates](docs/STATUS.md).

## Supported disc

| Property | Required value |
|---|---|
| Disc ID | `ULUS-10202` |
| Version | USA v1.00 |
| ISO size | `1,393,426,432` bytes |
| ISO SHA-1 | `706191720f78fe639eac20d3302d03b36a88e8e9` |
| Main module | `PSP_GAME/SYSDIR/BOOT.BIN` |
| Main-module SHA-1 | `8cf6d47bc812be7a8cfcd3c9d35b5cd53d8fff7d` |

Extraction fails before writing output when the size, disc hash, or required
file hashes differ.

## Requirements

- Windows 10/11 x64
- Python 3.11 or newer
- Git
- CMake 3.25 or newer and Ninja
- Visual Studio 2022 Build Tools with clang-cl and a Windows SDK

## Setup manager (recommended)

Run the source-install manager from a clone:

```powershell
python tools\mgspo\manager.py
```

Windows users can also double-click `Setup.bat` in the repository root.

Select the supported USA ISO, choose the software or experimental D3D12
runtime, and select **Build & Install**. The manager:

- checks the Visual Studio, clang-cl, Git, CMake, Ninja, and Python tools;
- verifies the exact ISO size and SHA-1 before extraction;
- initializes the pinned submodule, extracts private files, generates native
  code, configures, builds, and stages a local installation;
- keeps the selected ISO path in ignored `build/mgspo/manager.json`; and
- can edit restart-required graphics settings, open the native control
  remapper, and launch the installed runtime.

It does not download tools, copy the ISO into the installation, or make game
data redistributable. The standard Windows Python distribution must include
Tkinter. Run `python tools\mgspo\manager.py --diagnose` for a console-only
requirements check.

For terminal-only extraction, generation, build, installation, and validation,
see [Advanced installation](docs/ADVANCED_INSTALLATION.md).

## Default controls

| PSP input | Keyboard | XInput-style controller |
|---|---|---|
| Analog stick | W/A/S/D | Left stick |
| D-pad | Arrow keys | D-pad |
| Start | Enter | Start/Menu |
| Select | Shift | Back/View |
| Circle | G | East/B |
| Cross | Space | South/A |
| Square | F | West/X |
| Triangle | R | North/Y |
| L / R | Q / E | Shoulders or triggers |

Portable Ops uses Circle to confirm its menus.

## Settings

The first interactive launch creates `graphics.ini` and `input.ini` beside
the executable and opens the graphics and control dialogs. Reopen them
without starting the game:

```powershell
out\build\clang-cl\MGSPortableOps.exe --configure
out\build\clang-cl\MGSPortableOps.exe --configure-input
```

During gameplay, press **F1** to pause guest execution and open the native
settings hub. Keyboard, mouse, XInput-style controller bindings, dead zones,
response curves, inversion, and twin-stick options save atomically and apply
immediately. The remapper accepts up to four comma-separated bindings per
action; its capture button supports keyboard, mouse, and XInput controls.

Renderer selection, internal resolution (1x-8x), texture upscaling (1x-5x),
D3D12 shading rate, SMAA, and startup skipping are saved for the next launch.
The F1 hub enables **Restart Now** whenever saved graphics settings differ
from the active renderer configuration. Live renderer/resource recreation is
deliberately not attempted yet.

## Why `psp-recomp`

Portable Ops uses a large main PRX, three plaintext service PRXs, encrypted
firmware modules, and 106 plaintext stage overlays. The shared runtime already
supports the dynamic PRX lifecycle, interpreted/native handoff, overlay
identity, D3D12 rendering, audio, media, savedata, and profiling developed for
the Metal Gear Acid projects.

[`ccbury/MGSPOStaticRecomp`](https://github.com/ccbury/MGSPOStaticRecomp) is
useful behavioral research, but this project does not copy its implementation.
That repository currently exposes no license, and all tracked title facts here
are measured independently from the supported disc.

## Documentation

- [Status and next gates](docs/STATUS.md)
- [Task list and milestone gates](docs/TODO.md)
- [Advanced installation](docs/ADVANCED_INSTALLATION.md)
- [Measured findings](docs/FINDINGS.md)
- [Reproduction steps](docs/REPRODUCTION.md)
- [Shared-toolkit opportunities](docs/UPSTREAM.md)

## License

This project is GPL-2.0-or-later, matching the combined
`psp-recomp`/PPSSPP runtime obligations. Metal Gear Solid: Portable Ops and
its assets are not included and remain the property of their respective
rights holders.

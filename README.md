# Metal Gear Solid: Portable Ops Recomp

Source-only Windows static recompilation work for **Metal Gear Solid:
Portable Ops (ULUS-10202 v1.00)** using
[`psp-recomp`](https://github.com/Tzeentchnet/psp-recomp).

No game executable, generated game C, disc data, save data, trace, or capture
belongs in this repository. Supply your own supported USA disc image.

## Status

**Bootstrap / static translation.**

The supported disc is verified, its executable and module topology are
inventoried, and the complete main module generates and compiles:

- 19,671 accepted guest functions;
- 228 generated C chunks plus one registration unit;
- zero trapping stubs;
- strict `psp-recomp` revision verification; and
- successful clang-cl Release compilation.

This is **not yet a bootable or playable release**. Portable Ops' initial
module-start thread state has not been measured from a PPSSPP interpreter
trace, so the repository intentionally does not build a standalone game
driver. See [docs/STATUS.md](docs/STATUS.md).

## Supported input

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

## Bootstrap

Initialize the pinned runtime:

```powershell
git submodule update --init --recursive
```

Verify and extract private build inputs:

```powershell
python tools\mgspo\extract.py `
  "D:\Games\Metal Gear Solid - Portable Ops (USA).iso"
```

Generate the relocated image and native C:

```powershell
python tools\mgspo\gen.py
```

From an x64 Visual Studio developer shell, configure and compile:

```powershell
cmake --preset clang-cl
cmake --build --preset clang-cl
```

Generated and extracted files remain under ignored `build/` and `out/`
directories.

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
- [Measured findings](docs/FINDINGS.md)
- [Reproduction steps](docs/REPRODUCTION.md)
- [Shared-toolkit opportunities](docs/UPSTREAM.md)

## License

This project is GPL-2.0-or-later, matching the combined
`psp-recomp`/PPSSPP runtime obligations. Metal Gear Solid: Portable Ops and
its assets are not included and remain the property of their respective
rights holders.

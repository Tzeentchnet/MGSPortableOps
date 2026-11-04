# Reproduction

## 1. Initialize source dependencies

```powershell
git submodule update --init --recursive
python tools\mgspo\toolkit_identity.py --toolkit external\psp-recomp
```

The identity check requires the exact clean commit recorded in
`config/mgspo.toml`.

## 2. Verify and extract the supported disc

```powershell
python tools\mgspo\extract.py `
  "D:\Games\Metal Gear Solid - Portable Ops (USA).iso"
```

Expected final summary:

```text
109 plaintext and 22 encrypted PRXs
```

All extracted content is private and ignored under `build/mgspo/disc`.

## 3. Generate native C

```powershell
python tools\mgspo\gen.py
```

Expected code-generation summary:

```text
19671/19671 functions (0 trapping stubs)
229 translation units
```

The generator writes an exact toolkit-identity manifest and publishes output
only after validating its local control-flow labels.

## 4. Compile

Open an x64 Visual Studio 2022 developer shell:

```powershell
cmake --preset clang-cl
cmake --build --preset clang-cl
```

The `mgspo_bootstrap` target builds:

- the generated `mgspo_game` static library; and
- the strict title module-policy object.

No executable is expected at this milestone.

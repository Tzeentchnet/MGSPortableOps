# Reproduction

## GUI source-install manager

The recommended source-user path is:

```powershell
python tools\mgspo\manager.py
```

Choose the exact supported ISO, a software or experimental D3D12 build, and a
local install directory. **Build & Install** checks the toolchain, verifies the
disc identity, initializes the pinned submodule, extracts private inputs,
generates code, configures/builds the selected preset, and runs CMake install.
The manager streams each command and fails on the first nonzero result.

Console-only diagnostics and automation are also available:

```powershell
python tools\mgspo\manager.py --diagnose
python tools\mgspo\manager.py `
  --build-install `
  --build software `
  --iso "D:\Games\Metal Gear Solid - Portable Ops (USA).iso" `
  --install-dir out\install\MGSPortableOps-software
```

The selected ISO path is private local state under ignored
`build\mgspo\manager.json`. The install contains the executable, private
generated image, required runtime assets, and project documents, but not the
ISO.

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
523 files, 109 plaintext and 22 encrypted PRXs
```

All extracted content is private and ignored under `build/mgspo/disc`. The
complete tree is used at runtime; `build/mgspo/disc_inventory.json` records its
verified ISO identity and PRX inventory.

## 3. Generate native C

```powershell
python tools\mgspo\gen.py
```

Expected code-generation summary:

```text
19671/19671 functions (0 trapping stubs)
native module zlib: 118 functions, 3 translation units
232 translation units
```

The generator writes an exact toolkit-identity manifest and publishes output
only after validating its local control-flow labels. The total consists of 228
main chunks plus one main registration unit and two ZLIB chunks plus one ZLIB
registration unit.

## 4. Build the standalone runtime

Open an x64 Visual Studio 2022 developer shell:

```powershell
cmake --preset clang-cl
cmake --build --preset mgspo-runtime
```

The build produces `out\build\clang-cl\MGSPortableOps.exe` and stages the
private relocated image, PSP fonts, and VFPU tables beside it. Verify the
measured launch contract and whole-device UMD behavior with the supported ISO:

```powershell
$env:PSP_ISO = "D:\Games\Metal Gear Solid - Portable Ops (USA).iso"
out\build\clang-cl\MGSPortableOps.exe --verify-contract
```

Expected result:

```text
OK: boot image, native entry, measured state, exact encrypted module policy, plaintext load/unload, title HLE overrides, UMD block-device semantics, and ATRAC frame sizing are active; VFPU vasin and vsgn are verified ...
```

The contract loads and unloads the exact ZLIB, SOUND2, and KJFS images twice,
checks allocator reuse and stale-export removal, accepts the exact encrypted
`libfont.prx`, and explicitly rejects mismatched and unknown encrypted
identities. The rejection diagnostics before the final `OK` line are expected.

Stage a local installation manually:

```powershell
cmake --install out\build\clang-cl `
  --prefix out\install\MGSPortableOps-software
```

Reopen settings without booting the guest:

```powershell
out\build\clang-cl\MGSPortableOps.exe --configure
out\build\clang-cl\MGSPortableOps.exe --configure-input
```

On an interactive run, press F1 to pause guest execution and open the runtime
settings hub. Input changes apply immediately. Graphics changes are saved for
the next process and enable **Restart Now** in the hub.

Verify the measured plaintext callback and thread lifecycle:

```powershell
python tools\mgspo\module_lifecycle.py `
  out\build\clang-cl\MGSPortableOps.exe `
  $env:PSP_ISO `
  --out build\mgspo\standalone\module-lifecycle
```

Expected result:

```text
OK: plaintext module start, worker, and stop lifecycle matches the measured contract
```

The probe checks exact start/stop callback addresses, priority, stack, GP,
arguments, SP/K0/RA reset state, callback exit status, SOUND2's no-entry
behavior, KJFS `preseek` and `dbr` creation, and reverse-order stopping. Use
`--interpreted-zlib` to exercise the same callbacks without generated ZLIB.
The output directory must not already exist.

Launch the Win32/GDI software-renderer build with the supported disc:

```powershell
$env:MGSPO_DISC_ROOT = "$PWD\build\mgspo\disc"
out\build\clang-cl\MGSPortableOps.exe
```

Startup verifies the exact ISO size and SHA-1 before guest execution. Missing
or mismatched media fails closed. When `MGSPO_DISC_ROOT` is set, the extracted
tree is authoritative for file bytes; missing or size-mismatched entries also
fail closed.

Write structured diagnostics without enabling the verbose text logs:

```powershell
out\build\clang-cl\MGSPortableOps.exe `
  --log build\mgspo\runtime.jsonl
```

The JSON Lines stream includes imports, syscall returns, module and thread
lifecycle, display-list calls, file failures, runtime events, and fatal errors.
Set `MGSPO_LOG_CATEGORIES` to a comma-separated subset such as
`module,thread,fatal` when only those categories are needed.

## 5. Reproduce the private boot oracle

The oracle requires an x64 Visual Studio 2022 installation. Its wrapper selects
the exact pinned PPSSPP commit and patch, removes conflicting WinLibs entries
from the child build environment, and records the compiler and SDK identities.

```powershell
python tools\mgspo\oracle.py verify-config
python tools\mgspo\oracle.py prepare
python tools\mgspo\oracle.py build
```

Capture two independent runs with the supported ISO:

```powershell
python tools\mgspo\oracle.py capture `
  "D:\Games\Metal Gear Solid - Portable Ops (USA).iso" `
  build\mgspo\oracle\captures\boot-a

python tools\mgspo\oracle.py capture `
  "D:\Games\Metal Gear Solid - Portable Ops (USA).iso" `
  build\mgspo\oracle\captures\boot-b

python tools\mgspo\oracle.py compare `
  build\mgspo\oracle\captures\boot-a `
  build\mgspo\oracle\captures\boot-b
```

Expected comparison:

```text
OK: boot state, events, stack, and 100000 CPU steps match
```

Each output directory must not already exist. Captures use an isolated
memstick and a fixed RTC epoch, and contain a manifest with the disc, module,
PPSSPP revision, patch, executable, compiler, SDK, trace schema, trace bound,
and runtime settings. Raw state, stack, trace, event, memstick, and manifest
files remain ignored under `build/mgspo/oracle`.

## 6. Build and compare a bounded standalone trace

```powershell
cmake --preset clang-cl-trace
cmake --build --preset mgspo-trace

$env:PSP_ISO = "D:\Games\Metal Gear Solid - Portable Ops (USA).iso"
$env:MGSPO_DISC_ROOT = "$PWD\build\mgspo\disc"
New-Item -ItemType Directory -Force build\mgspo\standalone | Out-Null
out\build\clang-cl-trace\MGSPortableOps.exe `
  --headless `
  --trace build\mgspo\standalone\boot.trace `
  --log build\mgspo\standalone\boot.jsonl

python tools\mgspo\oracle.py compare-trace `
  build\mgspo\oracle\captures\boot-a\cpu.trace `
  build\mgspo\standalone\boot.trace
```

The trace build stops after exactly 100,000 instructions and writes
`boot.trace.done`. The comparator requires that completion marker and reports
the first PC/register/memory divergence with nearby context. A complete match
prints:

```text
OK: 100000 standalone CPU steps match the oracle
```

The Milestone 2 exit gate repeated this command with five distinct checkpoint
names. All five runs completed at exactly 100,000 steps and matched the oracle.

### Compare bounded KJFS service calls

After building the pinned PPSSPP oracle and the production runtime, capture
the same opt-in cases against each implementation:

```powershell
$iso = "D:\Games\Metal Gear Solid - Portable Ops (USA).iso"
$captures = "build\mgspo\oracle\captures"

python tools\mgspo\service_oracle.py capture-reference `
  $iso "$captures\kjfs-reference"
python tools\mgspo\service_oracle.py capture-candidate `
  out\build\clang-cl\MGSPortableOps.exe $iso "$captures\kjfs-native"
python tools\mgspo\service_oracle.py capture-candidate `
  out\build\clang-cl\MGSPortableOps.exe $iso "$captures\kjfs-interpreted" `
  --interpreted-zlib

python tools\mgspo\service_oracle.py compare `
  "$captures\kjfs-reference" "$captures\kjfs-native"
python tools\mgspo\service_oracle.py compare `
  "$captures\kjfs-reference" "$captures\kjfs-interpreted"
```

Each comparison should report `KJFS service comparison matched 20 cases`.
Every capture directory must be new and under the ignored
`build\mgspo\oracle\captures` directory. Captures contain private data,
isolated memsticks, manifests, completion markers, and file hashes. The tool
checks the pinned PPSSPP build and patch, disc and KJFS identities, capture
integrity, exact call inputs, results, full read buffers, and guard bytes.
Optional `--start` and `--stop` select a bounded case range; not every range
returns within the instruction limit. A timeout, missing completion marker, or
failed case is not a successful comparison.

The direct-file `.` and repeated-separator cases can be compared separately.
Pass `--disc-root` explicitly to exercise the extracted tree:

```powershell
python tools\mgspo\service_oracle.py capture-reference `
  $iso "$captures\kjfs-path-reference" --start 50 --stop 54
python tools\mgspo\service_oracle.py capture-candidate `
  out\build\clang-cl\MGSPortableOps.exe $iso "$captures\kjfs-path-tree" `
  --start 50 --stop 54 --disc-root build\mgspo\disc
python tools\mgspo\service_oracle.py compare `
  "$captures\kjfs-path-reference" "$captures\kjfs-path-tree"
```

This comparison should report four matching cases. Omit `--disc-root` to
exercise ISO-backed files, and add `--interpreted-zlib` to test interpreter
fallback. Candidate manifests record the selected mount and source hashes.

The natural size-driven canonical-file transfer is stages 54 through 57:

```powershell
python tools\mgspo\service_oracle.py capture-reference `
  $iso "$captures\kjfs-v4-file-reference" --start 54 --stop 58
python tools\mgspo\service_oracle.py capture-candidate `
  out\build\clang-cl\MGSPortableOps.exe $iso `
  "$captures\kjfs-v4-file-native" --start 54 --stop 58
python tools\mgspo\service_oracle.py capture-candidate `
  out\build\clang-cl\MGSPortableOps.exe $iso `
  "$captures\kjfs-v4-file-interpreted" --start 54 --stop 58 `
  --interpreted-zlib

python tools\mgspo\service_oracle.py compare `
  "$captures\kjfs-v4-file-reference" "$captures\kjfs-v4-file-native"
python tools\mgspo\service_oracle.py compare `
  "$captures\kjfs-v4-file-reference" "$captures\kjfs-v4-file-interpreted"
```

Both comparisons should report four matching cases. The read count is the
preceding size result rather than a fixed fixture. The verifier requires the
exact PPSSPP payload, `0xffffffff` completion sentinel, unchanged buffer
suffix, and unchanged external guards. Before capture, it also verifies that
the ISO has no physical `stage/init/data.cnf`, parses the indexed
`stage/init/_zar` resource, checks the exact 59-byte `data.cnf` entry, and
records the container and entry identities in both manifests.

This proves a successful nonempty KJFS `_zar` archive-entry transfer. It is not
evidence of an entry lookup inside the nested QAR or DAR containers, nor of
complete normalization, error, repeated-read, or asynchronous semantics.
These service comparisons do not validate ZLIB decompression or SOUND2.

Additional bounded ranges cover the currently returning edge cases:

- `--start 26 --stop 28`: dotted archive path plus close;
- `--start 30 --stop 31`: missing archive entry open;
- `--start 35 --stop 42`: null destination followed by a second open/read
  sequence; and
- `--start 38 --stop 42`: the second sequence in a clean probe: open,
  zero-count read, 64-count read, and close.

Append one range to each reference and candidate capture command and use new
output directories. The comparison should report two, one, seven, and four
matching cases respectively. The zero-count read still writes the complete
59-byte archive entry; the following read advances internal state and writes a
different exact buffer. The verifier compares both full 64-byte buffers and
both external guards. The five deliberately non-returning cases use a separate bounded retry
contract. Capture each stage against PPSSPP and both standalone ZLIB modes:

```powershell
$blockedStages = 20, 28, 31, 43, 45

foreach ($stage in $blockedStages) {
  python tools\mgspo\service_oracle.py capture-blocked-reference `
    $iso "$captures\kjfs-v5-blocked-$stage-reference" `
    --stage $stage --retries 8
  python tools\mgspo\service_oracle.py capture-blocked-candidate `
    out\build\clang-cl\MGSPortableOps.exe $iso `
    "$captures\kjfs-v5-blocked-$stage-native" `
    --stage $stage --retries 8
  python tools\mgspo\service_oracle.py capture-blocked-candidate `
    out\build\clang-cl\MGSPortableOps.exe $iso `
    "$captures\kjfs-v5-blocked-$stage-interpreted" `
    --stage $stage --retries 8 --interpreted-zlib

  python tools\mgspo\service_oracle.py compare `
    "$captures\kjfs-v5-blocked-$stage-reference" `
    "$captures\kjfs-v5-blocked-$stage-native"
  python tools\mgspo\service_oracle.py compare `
    "$captures\kjfs-v5-blocked-$stage-reference" `
    "$captures\kjfs-v5-blocked-$stage-interpreted"
}
```

Each comparison must report that its stage matched for eight retries. Stage 43
automatically runs range 42-44 so the direct file is opened before the
negative seek; the other cases run only their blocked stage. A successful
capture requires the exact operation, optional asynchronous wait and 64-bit
result, one-thread continuity, one-second callback delay, retry count, and
`service.blocked` marker. A timeout, instruction-limit exit, crash, unexpected
exported-call return, or missing marker is always a failure.

## 7. Run the deterministic first-mission checkpoint

Build the production runtime, then run:

```powershell
$iso = "D:\Games\Metal Gear Solid - Portable Ops (USA).iso"

python tools\mgspo\smoke.py `
  out\build\clang-cl\MGSPortableOps.exe `
  $iso `
  --out build\mgspo\standalone\first-mission
```

The output directory must not already exist. The tool uses:

- the tracked `config/routes/first-mission.pad` presentation-clock route;
- a new isolated memory stick and profile name `PLAYER`;
- deterministic utility-dialog responses;
- the software renderer with PSP VBlank pacing enabled;
- exact active-overlay identities to finish the opening media sequence;
- a forward analog interval after mission entry;
- native ZLIB at the measured `0x08b20000` base by default;
- repeated pause input until the pause-menu signature remains visible for ten
  VBlanks and its animated red highlight reaches the measured 5551 capture
  phase; and
- the expected static pause-region SHA-256 from `config/mgspo.toml`.

Success requires:

- creation of save `ULUS10202001`;
- loading raw path `disc0:/sce_lbn0x68110_size0x10c724` at `0x08b86f00`;
- no unimplemented import, interpreter trap, or bare-UMD lookup failure;
- no interpreted ZLIB profile entry;
- the explicit `first-mission pause checkpoint reached` marker before the
  presentation-7,200 failure limit; and
- SHA-256
  `39751fb212b51863b6d2dbb2d4c1861e022cf4c6c983573998c161ff14ad0ae3`
  for rectangle `[0, 0, 240, 272]`.

Expected output:

```text
OK: clean-save route reached the stable first-mission pause checkpoint; frame region SHA-256 39751fb212b51863b6d2dbb2d4c1861e022cf4c6c983573998c161ff14ad0ae3
```

The recorded repeatability gate ran this command five consecutive times with
distinct output directories. Every run created a fresh profile, observed six
ordered overlay unloads, reused both `0x08afb800` and `0x08b86f00`, loaded the
same mission identity, reached the checkpoint at presentation 7,068, and
produced the same static-region hash. The complete private PPM remains
available for diagnosis; its animated tactical-map half is not part of this
runtime repeatability hash. Use `--interpreted-zlib` to compare against
interpreter fallback or `--turbo` for non-acceptance profiling.

The text log, save, and PPM capture remain under the ignored output directory.
A `summary.json` records the checkpoint, plaintext start lifecycle, reused
overlay bases, full and region hashes, ZLIB mode, save identity, interpreter
profile, and host elapsed time. The verifier parses
its potentially large structured JSON log and deletes it after a successful
run; pass `--keep-structured-log` to retain that private diagnostic file.

### Experimental D3D12 and per-flip diagnostics

The production preset remains software-only. In the same developer shell,
build the separate experimental preset:

```powershell
cmake --preset clang-cl-d3d12-experimental
cmake --build --preset mgspo-d3d12-experimental
cmake --build out\build\clang-cl-d3d12-experimental `
  --target mgspo_d3d12_write_sync_test
out\build\clang-cl-d3d12-experimental\mgspo_d3d12_write_sync_test.exe
```

The preset searches for the SDL3 shared development package and, if absent,
fetches SDL3 3.2.20 from its official release with a pinned SHA-256. To avoid
the download, provide `SDL3_DIR` and set `MGSPO_FETCH_SDL3=OFF` when
configuring. The downloaded package and runtime DLL remain in the separate
build directory.

For a normally paced, native-resolution diagnostic, use a fresh output
directory:

```powershell
$out = "build\mgspo\standalone\d3d12-profile"
$env:SR_D3D12_SCALE = "1"
$env:SR_D3D12_VRS = "0"
$env:SR_D3D12_STAGE_LOG = "1"
$env:SR_D3D12_VERTEX_LOG = "1"
$env:SR_D3D12_FRAMEBUFFER_LOG = "1"
$env:MGSPO_D3D12_READ_TRACE = "1"
$env:SR_PERF_START = "6000"
$env:SR_PERF_WINDOW = "60"
$env:SR_PERF_FRAME_BUDGET_MS = "33.333333"
$env:SR_PERF_FILE = Join-Path (Get-Location) "$out\frames.csv"

python tools\mgspo\smoke.py `
  out\build\clang-cl-d3d12-experimental\MGSPortableOps.exe `
  $iso --renderer d3d12 --out $out

python tools\mgspo\perf_report.py "$out\frames.csv" `
  --min-present 6901 --max-present 6999 --out "$out\report.json"

python tools\mgspo\frame_diff.py `
  build\mgspo\standalone\first-mission\capture_first_mission_pause.ppm `
  "$out\capture_first_mission_pause.ppm" --region 0 0 240 272 `
  --out "$out\frame-diff.json"
```

The smoke test requires the requested backend, the write-synchronization
barrier, at least one safely batched CPU-presentation readback, no observed
newer-framebuffer invalidation or current-generation batching refusal, and the
same exact static region hash as the software run. The experimental executable
defaults to the measured hardware texture path and logs
`mgspo: D3D12 hardware texture path enabled (title default)`. The current
default route matches all 65,280 pixels in the stable region without a
tolerance. This is one software-reference checkpoint, not a PPSSPP graphics
acceptance test; the tactical-map half is animated and not phase-aligned.

Set `SR_GPU_PSP_SAMPLER=1` only to restore the toolkit's integer-quantized
texture path for A/B diagnosis. That mode reproduced the earlier 22-pixel
stable-region difference and is intentionally rejected by the D3D12 smoke
contract. The switch also changes texture-combine arithmetic, so it does not
isolate sampling alone. Set
`MGSPO_D3D12_BATCH_PRESENT_READBACK=0` only for an A/B diagnostic of the
original per-pixel fallback. `MGSPO_D3D12_READ_TRACE=1` identifies complete
`480x272` CPU-presentation read sequences and the overlapping target
generations; omit it for ordinary runs.
The log, capture, and complete performance CSV remain private for diagnosis.
The report labels repeated and skipped presentation counts, aligns delayed
GPU samples by source flip, marks unavailable backend timing as missing, and
lists up to five intervals with the most framebuffer readbacks. Each listed
interval is identified by its ending flip and presentation count; its backend
present time belongs to the preceding flip and may be unavailable. Set
`SR_PERF_START=0` and omit the report's presentation bounds to investigate the
whole route.
The frame comparison reports exact RGB differences and returns exit code 1
when the selected region differs; its signed histogram counts changed channels
as candidate minus reference, and it does not apply an assumed tolerance.
Stage and framebuffer logging can perturb measurements. `over_budget` reflects
the capture-time setting, which the CSV does not record; retain that setting
with the results. Compare matching workload counters, visuals, and audio
before drawing performance conclusions.

To repeat the bounded 1x/2x/4x resolution sweep without the perturbing
diagnostic logs, run each scale sequentially:

```powershell
$expectedRegions = @{
  1 = "39751fb212b51863b6d2dbb2d4c1861e022cf4c6c983573998c161ff14ad0ae3"
  2 = "cd5251127a54ef2de7db3a196e9cedef463cdb59b0b1ed5b703d77fbc965d16c"
  4 = "f04a4b3b531c88d23429ebf6fd838edf728f850772704db93c5df0ae0afe2773"
}

foreach ($scale in 1, 2, 4) {
  $out = "build\mgspo\standalone\perf-d3d12-resolution-${scale}x"
  $env:SR_D3D12_SCALE = "$scale"
  $env:SR_D3D12_VRS = "0"
  $env:SR_PERF_START = "6000"
  $env:SR_PERF_WINDOW = "60"
  $env:SR_PERF_FRAME_BUDGET_MS = "33.333333"
  $env:SR_PERF_FILE = Join-Path (Get-Location) "$out\frames.csv"

  python tools\mgspo\smoke.py `
    out\build\clang-cl-d3d12-experimental\MGSPortableOps.exe `
    $iso --renderer d3d12 --out $out `
    --expected-frame-region-sha256 $expectedRegions[$scale]

  python tools\mgspo\perf_report.py "$out\frames.csv" `
    --min-present 6901 --max-present 6999 `
    --out "$out\report.json"
}
```

Use fresh output names for a second repeat. The 2x and 4x expected hashes are
repeatability identities observed twice, not PPSSPP or software correctness
references. Omitting their overrides intentionally makes the smoke test reject
those scales against the accepted 1x hash. Compare delayed GPU timings by
source flip and normalize them against the recorded draw/vertex workload;
paced host-flip rate is not guest-visible FPS.

## 8. Interactive controls

The default keyboard layout is:

| PSP input | Key |
|---|---|
| Analog stick | W/A/S/D |
| D-pad | Arrow keys |
| Start / Select | Enter / Shift |
| Circle / Cross | G / Space |
| Square / Triangle | F / R |
| L / R | Q / E |

An XInput-style controller maps the PSP analog stick to the left stick, the
PSP face buttons by position, and L/R to the shoulders or triggers. Portable
Ops uses Circle to confirm menus.

The experimental D3D12 route is visually equivalent to the software
checkpoint at 1x only. The repeatable 2x and 4x regions differ from that
accepted hash. PPSSPP pixel comparison, audio, complete mission controls,
10-minute stability, and the 30 FPS acceptance test remain pending.

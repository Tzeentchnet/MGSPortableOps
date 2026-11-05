# Status

> **First-mission bring-up; not yet a playable release.**

The standalone runtime has complete static translation with no trapping
stubs, strict source and module identity checks, deterministic entry into the
first controllable prison mission, and matching software/D3D12 output at the
accepted 1x pause checkpoint. The measured route can move Snake forward,
render the HUD and radar, enforce bed collision, and open the pause menu.
Complete gameplay systems, audio correctness, broader visual comparison,
10-minute stability, and the 30 FPS acceptance gate remain open.

## Current milestone

Milestone 3 remains open: module and I/O reliability through first-mission
entry. Later milestones have partial evidence, but their exit gates are not
complete.

Completed:

- exact ULUS-10202 ISO, executable, runtime, and PPSSPP revision pinning;
- complete generation of 19,671 accepted main-module functions and 118 ZLIB
  functions with no trapping stubs across 232 translation units;
- deterministic PPSSPP boot-state capture and two identical
  100,000-instruction interpreter traces;
- production and trace-enabled standalone Windows executables;
- exact standalone/oracle agreement for all 100,000 bounded CPU steps,
  including a post-mission-bring-up regression run;
- a complete 523-file private extraction with ISO-backed path, order, LBA,
  size, and identity checks;
- project-owned HLE, scheduler, module, interpreter, OSK, logging, and VFPU
  compatibility layers without modifying the pinned `psp-recomp` checkout;
- PPSSPP-compatible whole-device `umd0:`, `umd1:`, and `umd:` sector I/O,
  ioctls, asynchronous reads, and executable contract checks;
- 20 KJFS probe calls matching PPSSPP in both native- and interpreter-ZLIB
  modes, including guarded read buffers and direct-file seeks through and
  beyond EOF; four additional direct-file open/close cases for `.` and
  repeated separators match on ISO-backed and extracted-tree mounts, and the
  natural size-driven 59-byte `data.cnf` archive entry from `stage/init/_zar`
  matches exactly; isolated ranges also match dotted/missing entry opens, a
  null destination, and consecutive zero/64-count archive reads; five
  non-returning path/open/seek cases additionally match as eight exact,
  causally observed syscall retry cycles with clean completion markers in
  both ZLIB modes;
- executable plaintext-module contracts covering exact hashes, import/export
  parsing, relocation-derived metadata, GP/entry offsets, load/unload,
  allocator reuse, and stale-export removal;
- an exact `libfont.prx` encrypted-module policy with fail-closed mismatched
  and unknown identity checks;
- software-rendered publisher, title, menu, profile, savedata, difficulty,
  cutscene, loading, pause, and first-mission output;
- deterministic cutscene skipping and clean-profile creation;
- exact identification of the first mission overlay as
  `PSP_GAME/USRDIR/stage/st04vo/st04vo.prx`, loaded at `0x08b86f00`;
- a tracked presentation-clock input route plus exact-overlay media automation
  and an automated clean-save first-mission verifier;
- native ZLIB at its measured `0x08b20000` base, backed by an exact module
  identity, 100,000-step PPSSPP trace agreement, and zero interpreted ZLIB
  targets on the mission route;
- a stable pause-menu region SHA-256 of
  `39751fb212b51863b6d2dbb2d4c1861e022cf4c6c983573998c161ff14ad0ae3`;
- exact experimental D3D12 agreement with the software renderer for all
  65,280 pixels in that stable pause region using the title-default hardware
  texture path;
- five consecutive native-ZLIB clean-profile runs with identical mission
  identity, lifecycle order, save creation, and static-region hash; and
- a native F1 settings hub that pauses guest execution, immediate atomic
  keyboard/mouse/controller remapping with XInput capture, restart-explicit
  graphics configuration, and standalone `--configure` entry points;
- a Python/Tkinter clone manager that checks the build environment, verifies
  the exact supported ISO, runs extraction/generation/configure/build/install,
  writes restart-only graphics settings, opens the native remapper, and
  launches a locally staged runtime without copying the ISO; and
- visible forward movement and running animation, HUD/radar updates, bed
  collision, and pause-menu entry.

## Validation boundary

The measured launch contract remains exact. Both current Release executables
pass `--verify-contract`, including plaintext module load/unload and base
reuse, exact encrypted policy, UMD, ATRAC frame-size, VFPU `vasin`, and VFPU
`vsgn` checks. A separate lifecycle probe validates ZLIB, SOUND2, and KJFS
start/stop callbacks, exact module-thread state, KJFS worker creation, callback
exit status, and reverse-order stopping in both native- and
interpreter-ZLIB modes. The current trace build still matches the pinned
PPSSPP oracle for exactly 100,000 instructions, all Python tool tests pass,
and the pinned runtime submodule is clean at
`b56ff30ef5997b9f168209df8c33156e82402e7b`.

The clean-save smoke route creates an isolated memory stick, enters profile
name `PLAYER`, selects Normal difficulty, advances the remaining media screens
only while their exact overlays are active, loads `st04vo.prx`, moves Snake
forward, and repeatedly requests pause until its framebuffer signature remains
visible for ten VBlanks and the globally animated red highlight reaches the
measured 5551 capture phase. It then captures and exits cleanly; presentation
7,200 is only a failure limit. It rejects missing route milestones,
unimplemented imports, interpreter traps, UMD lookup failures, missing
savedata, unexpected encrypted modules, active allocation overlap, incorrect
module unload identity, missing reuse of `0x08afb800` or `0x08b86f00`,
plaintext start-callback or worker-thread drift, fatal structured events,
native ZLIB fallback, and static-region hash drift. The final five-run gate
reached the pause checkpoint at presentation 7,068,
recorded six successful overlay unloads per run, and reproduced the exact
`240x272` left-region hash. The animated tactical-map half can differ with
VBlank phase and is deliberately retained in the private capture but excluded
from this runtime repeatability hash.

After the byte-mode seek fix, another normally paced clean-save run reached
the same pause-region hash at presentation 7,065. After the path fix, a
normally paced run using the extracted tree reached it at presentation 7,067.
A separate `--turbo` run hit the presentation limit while the opening video
was active; turbo is a non-acceptance profiling mode and that result does not
establish a paced regression.

An isolated experimental D3D12 build reuses the pinned toolkit backend and
selects it explicitly for diagnostics. A normally paced run reached the
first-mission pause on an RTX 5070 and recorded actual GPU draw submissions.
The project now reads back overlapping GPU-newer targets before CPU writes,
and synchronizes VRAM once before the automated pixel scan. CPU presentation
fallbacks also batch older-generation target readbacks; this reduced a traced
whole route from 391,751 readbacks to 71 without changing its hardware-region
hash. The former framebuffer invalidation warnings did not recur. The
toolkit's integer-quantized texture path differed from software at 22 of
65,280 stable-region pixels by at most nine RGB levels. The title now defaults
the experimental build to the hardware texture path, which changed those
pixels to the exact software values. A fresh default route passed the tracked
region hash with zero differing pixels; default and concurrent stress routes
reported 70-71 readbacks. Because the toolkit switch affects both sampling and
texture-combine arithmetic, the precise source of the former difference
remains unresolved. No tolerance or PPSSPP visual reference has been approved.
See [FINDINGS.md](FINDINGS.md) for the diagnostic measurements and remaining
readback caveats.

A two-run, normally paced D3D12 sweep over presentations 6,901-6,999 measured
1x, 2x, and 4x internal resolution with full-rate shading. Workload-aligned
active GPU time averaged 1.246, 1.832, and 3.305 ms respectively on the RTX
5070; 2x was 1.47x and 4x was 2.65x the 1x GPU cost. Paced frame-time means
were 19.42, 21.05, and 19.62 ms, but scheduler/VSync sampling dominates that
non-monotonic result, so it is not guest FPS. All runs stayed below 34.05 ms
within this short interval. The 1x checkpoint retained its exact accepted
hash. The 2x and 4x hashes repeated across both runs but differed from 1x at
23,908 and 21,700 of 65,280 stable-region pixels, so higher-resolution visual
correctness remains open despite the measured GPU headroom.

The route proves first-mission entry and a narrow slice of player control.
The settings work proves that the native dialogs can be opened both as
standalone configuration processes and from F1 in a running game. Input saves
replace `input.ini` atomically and update the live runtime configuration.
Graphics saves replace `graphics.ini` atomically but deliberately require a
process restart; renderer/resource recreation has not been made transactional.
The local manager and CMake install rules are source-user conveniences, not a
redistributable game package, and retain no ISO bytes in the installation.
The KJFS comparisons establish only the cases described in
[FINDINGS.md](FINDINGS.md). They prove a successful nonempty `_zar`
archive-entry transfer, including the title-observed `0xffffffff` completion
sentinel, plus exact bounded retry behavior for the five observed
non-returning path/open/seek cases and asynchronous seek completion. A natural
event stream indicates nested QAR/DAR entries are consumed title-side rather
than passed to an observed KJFS export; that consumer remains unvalidated.
ZLIB and SOUND2 service semantics, mission scripting, camera and combat
controls, AI, radio, audio, ten-minute stability, and correct real-time
performance remain unverified.

## Known limitations

- PPSSPP reference frames and pixel-diff tolerances have not been established.
- D3D12 is experimental. Its title-default texture path exactly matches the
  software renderer at 1x for the stable pause checkpoint. Repeatable 2x and
  4x captures differ from that accepted region; other checkpoints, PPSSPP
  visual comparison, the animated map at a matched VBlank phase, and CPU/GPU
  coherency beyond the observed route remain unverified.
- Earlier XAudio2 initialization failed with `0x80070490`; recent paced runs
  initialized it but reported substantial resynchronization. Audible playback,
  timing, and audio correctness remain unverified.
- SOUND2 remains the dominant interpreted hotspot. The accelerated profiling
  route measured 71,512,658 interpreted SOUND2 instructions after native ZLIB.
- Whole-device UMD asynchronous behavior is contract-tested but has not been
  observed on the current game route.
- Only forward analog movement and collision with the cell bed have been
  exercised. Camera, combat, items, CQC, interactions, radio, AI, damage, and
  restart behavior remain unverified.
- Runtime input capture currently recognizes keyboard, mouse, and XInput
  controls. DirectInput-only controllers can use named bindings but do not yet
  have press-to-capture support.
- Graphics changes require restart. Runtime renderer switching, target
  recreation, audio controls, release packaging, and automatic dependency
  installation are not implemented.
- No 10-minute gameplay or 30 FPS acceptance run has been completed.

## Next gates

1. Validate the title-side QAR/DAR consumers, ZLIB output/errors, and SOUND2
   streaming, synchronization, and timing against PPSSPP.
2. Capture matching PPSSPP software-renderer frames and define objective
   pixel-diff tolerances.
3. Extend the deterministic mission route through camera, combat, items,
   interactions, radio, AI, damage, pause/resume, and restart.
4. Complete three deterministic 10-minute mission runs.
5. Validate D3D12 against the software/PPSSPP checkpoints.
6. Profile the measured route and meet the documented 30 FPS thresholds.

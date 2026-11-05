# Findings

## MGSPO-F-001 - Supported disc identity

**Status:** Confirmed

The supported source is the USA ULUS-10202 image:

- size `1,393,426,432` bytes;
- SHA-1 `706191720f78fe639eac20d3302d03b36a88e8e9`;
- `BOOT.BIN` SHA-1
  `8cf6d47bc812be7a8cfcd3c9d35b5cd53d8fff7d`; and
- `EBOOT.BIN` SHA-1
  `a82d16ef4a4db93b4217429a4e2ffa16f160fc3d`.

The extraction tool verifies all four values before publishing private build
inputs.

## MGSPO-F-002 - Module topology

**Status:** Confirmed

The disc contains 25 PRXs under `PSP_GAME/USRDIR/modules` and 106 PRXs under
`PSP_GAME/USRDIR/stage`.

Of the module PRXs, only these three are plaintext ELF images:

| Module | Size | SHA-1 |
|---|---:|---|
| `kjfs.prx` | 77,744 | `ed7376c5e42652f6554f664621e257a5c9ad26c6` |
| `sound2.prx` | 134,912 | `2bb43c7effe0e2454f13dfe3ba90abbce9a83dfd` |
| `zlibdec.prx` | 19,884 | `518c64f39a7492340cdcc3411044d555a4faae8d` |

All 106 stage PRXs are plaintext. The other 22 module PRXs are encrypted.

## MGSPO-F-003 - Main-module layout

**Status:** Confirmed

| Property | Value |
|---|---|
| Module | `mgp_main` |
| Base | `0x08804000` |
| Entry | `0x08804128` |
| GP | `0x08a07e90` |
| Text size | `0x001d6828` |
| Relocated image size | `0x002f77c0` |
| Import stubs | 240 across 32 libraries |

The pinned analyzer initially reports 19,676 candidates.

## MGSPO-F-004 - Import NID collides with the text range

**Status:** Confirmed

The `sound2` import NID `0x088749ad` numerically falls inside the main text
range. The shared analyzer's broad pointer heuristic initially treated it as a
function entry, despite MIPS instruction alignment making that impossible.

The title code-generation wrapper requires this exact candidate and rejects it.
Any different unaligned candidate fails generation.

## MGSPO-F-005 - Four internal labels are not functions

**Status:** Confirmed

The analyzer also promotes these internal or delay-slot addresses to function
entries:

- `0x08901fe4`
- `0x08901ffc`
- `0x08902000`
- `0x0896e664`

Control-flow inspection shows that the first three belong to the function at
`0x08901f78`; `0x08901ffc` is a return delay slot. `0x0896e664` is a JAL delay
slot inside a larger function. Treating either delay slot as a function
produces an unresolved self-label in generated C.

The wrapper requires and excludes these exact candidates. Generation also
checks every generated function for unresolved local labels before publishing
output.

## MGSPO-F-006 - Static translation gate

**Status:** Confirmed

After the five evidence-backed exclusions, code generation emits 19,671 of
19,671 functions with zero trapping stubs. The output is 228 split C
translation units plus one registration unit and compiles successfully with
clang-cl 19.1.5 in Release mode.

## MGSPO-F-007 - Boot contract

**Status:** Confirmed

Two independent interpreter-only captures from PPSSPP v1.20.4 commit
`fa50bb1976065c4f8b1b47af227d367fe9771555` produced byte-identical initial
state, prepared stack, event log, and 100,000-instruction CPU trace.

| Property | Measured value |
|---|---:|
| Module UID | `0x112` |
| Module-start thread UID | `0x113` |
| Next kernel UID | `0x114` |
| Priority | `0x20` |
| Requested attributes | `0x80000000` |
| Effective attributes | `0x800000ff` |
| Stack range | `0x09fffc00` - `0x0a000000` |
| Stack size | `0x400` |
| Entry PC | `0x08804128` |
| GP | `0x08a07e90` |
| Initial SP | `0x09fffe90` |
| Initial K0 | `0x09ffff00` |
| Initial RA | `0x08000030` |
| Argument address and size | `0x09fffed0`, 33 bytes |
| Initial GE list ID | `0` |

The exact argument bytes and reduced GPR, HI/LO, FPU, and VFPU reset state are
recorded in `config/mgspo.toml`. The private boot-state snapshot also records
the kernel, user, and volatile allocator layouts, the loaded module allocation,
and all live threads.

The first repeat attempt exposed the host wall clock through
`sceRtcGetCurrentClockLocalTime`. Oracle runs now pin Unix epoch `946684800`
and apply the configured 60-minute PSP timezone. No trace ranges or values are
ignored.

Original boot-pair evidence identities:

| Artifact | SHA-256 |
|---|---|
| PPSSPP oracle patch | `1f813e08031dc42454a0dd8a91072f535bd82cd2532e74badbbf07a77c3d1080` |
| `PPSSPPHeadless.exe` | `9058d885689ae6a68b28cdf80d74e2c865d4980222fb0674f28c20409b86cc00` |
| Boot state | `ae3fd18b480487989308e5a0073a3a28b6cffbf834e2eb22cbe5f944a2c39fa9` |
| Prepared stack | `d0e481fc998fd1c30806c46271b8cd9174896535fa03610a5a928e4ad0e2935c` |
| CPU trace | `7c9e735cbd36d26d601ad98b1c2c3fc0f6b03f873ad07f4e9e1a37e8c88d1dec` |
| Event log | `47b09d168984919a76e7b2b90984f8a07837211585fbe04bc49d61bffc6b5042` |

The oracle was built with MSVC 19.44.35229 for x64, VC tools 14.44.35207,
Visual Studio 17.14.42, and Windows SDK 10.0.26100.0.

## MGSPO-F-008 - Standalone bootstrap

**Status:** Confirmed

The standalone launcher now:

- loads the relocated main image from beside the executable;
- reconstructs the measured 1 KiB root stack and exact CPU/FPU/VFPU state;
- seeds the measured UID and GE counters and adopts that state in the
  scheduler rather than using the generic reset;
- registers generated native functions and the strict title module policy;
- uses the dependency-free Win32/GDI software path for initial bring-up;
- validates the supported ISO before guest execution;
- provides production and fixed 100,000-step trace build presets; and
- reports host faults with live guest registers, thread state, last NID,
  known main-module state, and recent trace context.

The generic runtime's clock, system parameters, WLAN identity, and OpenPSID do
not match the pinned PPSSPP settings. Project-owned HLE overrides provide the
measured fixed RTC, timezone/date settings, and MAC-derived identity without
modifying the pinned submodule. The runtime registry originally appended
duplicate NIDs and selected the first entry; a project-owned compilation
wrapper changes public title registrations to replace an existing NID.

Both production and trace executables pass `--verify-contract`, including the
prepared-stack SHA-256
`d0e481fc998fd1c30806c46271b8cd9174896535fa03610a5a928e4ad0e2935c`.

The standalone trace now matches the PPSSPP oracle for all 100,000
instructions. Five consecutive named headless runs independently reproduced
the exact match.

## MGSPO-F-009 - Runtime fidelity required title-specific transitions

**Status:** Confirmed

The complete bounded match required modeling behavior that is observable to
guest code but absent or different in the generic runtime:

- SDK-version register poisoning and PPSSPP semaphore errors;
- deleted-thread and module-return scheduler transitions;
- measured display H-count initialization;
- AV utility reservations and delays;
- disc-open, close, and first-directory-entry delays;
- the `0xffffffff` no-entry module sentinel;
- PPSSPP's runtime import-stub jump representation; and
- `SceIoDirEnt` zero-timestamp and private-padding behavior.

The accepted comparator normalization is limited to the equivalent patched
guest-import `j target` versus static `jr ra` stub representation. PCs,
register and memory writes, delay slots, and subsequent target execution must
still agree.

## MGSPO-F-010 - Private disc-tree and structured diagnostics

**Status:** Confirmed

Extraction publishes all 523 ISO files under the ignored
`build/mgspo/disc` tree after validating the exact ISO identity. When
`MGSPO_DISC_ROOT` is set, runtime file bytes come from that tree while the
verified ISO supplies canonical PSP path lookup, directory order, LBAs, and
sizes. Missing or size-mismatched extracted entries fail closed.

`--log PATH` writes unbuffered JSON Lines with a monotonic sequence. The
runtime emits typed records for imports, syscall returns, module lifecycle,
thread lifecycle, display-list calls, file failures, runtime state, and fatal
errors. The final bounded validation produced 854 well-formed, consecutively
numbered records while retaining exact trace agreement.

## MGSPO-F-011 - Whole-device UMD I/O is sector-based

**Status:** Confirmed

The post-title route opens `umd1:` as a file-like block device. PPSSPP
measurement established that `umd0:`, `umd1:`, and `umd:` are aliases for the
complete verified ISO rather than the ISO9660 root directory. Reads, seek
offsets, and resulting positions use 2,048-byte sectors; normal `disc0:` paths
and raw-LBN files remain byte-based.

The project-owned HLE wrapper implements those units for synchronous and
asynchronous reads and seeks, the UMD ioctls exercised by PPSSPP, sector EOF,
and explicit unsupported-command errors. Compile-time checks require the
supported ISO size to fit in the runtime's 32-bit file representation and to
contain complete sectors. The executable contract checks all aliases, sector
data, EOF, size/position ioctls, asynchronous sector reads, and unchanged
byte-mode behavior.

## MGSPO-F-012 - First-mission overlay identity and address reuse

**Status:** Confirmed

The deterministic route loads and replaces stage overlays in two recurring
allocation ranges. Representative identities are:

| Stage | Raw path | Size | SHA-1 | Runtime base |
|---|---|---:|---|---:|
| `title/title.prx` | `sce_lbn0x710d0_size0x498bc` | 301,244 | `9e4c4558609885baf87cc4e1b764929c371d77e3` | `0x08b86f00` |
| `r_main01/r_main01.prx` | `sce_lbn0x6a2e0_size0xc4c` | 3,148 | `a1a003c4c08b23ea9919e5e91a2decc9d2a79fc4` | `0x08afb800` |
| `r_main02/r_main02.prx` | `sce_lbn0x776a0_size0xc3c` | 3,132 | `f162b45cb8973046ac2274f835dca62e98e50311` | `0x08afb800` |
| `flashdemo/flashdemo.prx` | `sce_lbn0x58270_size0x34d84` | 216,452 | `3a5edff7166fa9635dbe7f536490d6f680c7e1eb` | `0x08b86f00` |
| `st04vo/st04vo.prx` | `sce_lbn0x68110_size0x10c724` | 1,099,556 | `7a32951a2e07132b4a92cabfb2c3a156ff5e205c` | `0x08b86f00` |

This proves runtime-selected stage loading and observable reuse of both overlay
bases through first-mission entry. It does not by itself complete the stronger
lifecycle requirement to test every unload callback and explicitly reject all
stale mappings.

## MGSPO-F-013 - SOUND2 requires additional VFPU operations

**Status:** Confirmed

Analog movement reaches SOUND2 code containing opcodes `0xd0176060` (`vasin`)
and `0xd04a0080` (`vsgn.p`). The pinned interpreter did not implement either
operation. A project-owned wrapper now supplies PPSSPP-compatible behavior
while leaving the `psp-recomp` submodule unchanged:

- `vasin` uses the existing bit-exact `sr_vfpu_asin()` kernel; and
- `vsgn` applies source/destination prefixes and classifies sign from the
  integer representation so signed zero and NaNs follow PPSSPP behavior.

Direct executable contract cases cover both observed opcodes. The movement
route then ran through presentation 7,000 without an interpreter trap.

## MGSPO-F-014 - Deterministic clean-save mission checkpoint

**Status:** Confirmed

`config/routes/first-mission.pad` is a presentation-clock route from process
launch through profile creation and Normal difficulty selection.
`tools/mgspo/smoke.py` supplies an isolated memory stick, deterministic
OSK/dialog responses, a forward analog interval, exact module checks, and a
bounded success condition. After presentation 5,700, title-owned input
automation advances media only while one of the measured pre-mission overlays
is active. It stops as soon as `st04vo` replaces those overlays.

After loading `st04vo/st04vo.prx` at `0x08b86f00`, the runtime requests pause
until the pause-menu signature remains visible for ten VBlanks, then waits for
the measured 5551 phase of its globally animated red highlight before
capturing. This avoids a load-sensitive alternate highlight level while the
presentation-7,200 limit remains a fail-closed timeout. The runtime writes the
interpreter profile and exits after capture. The exact SHA-256 of the static
left rectangle `[0, 0, 240, 272]` is:

```text
39751fb212b51863b6d2dbb2d4c1861e022cf4c6c983573998c161ff14ad0ae3
```

Five consecutive native-ZLIB clean-profile runs reached this checkpoint at
presentation 7,068 and reproduced the module identity, six ordered overlay
unloads, both reused overlay bases, save, and region hash. The complete PPM is
retained privately, but its tactical-map half has VBlank-driven animation and
is not used as an exact runtime hash. This checkpoint is a runtime
repeatability oracle, not yet a PPSSPP pixel-reference comparison.

## MGSPO-F-015 - Module identity and unload contracts

**Status:** Confirmed

The executable contract now reads the three plaintext services directly from
the verified ISO and checks their exact SHA-1 identities before loading them
in dependency order. For ZLIB, SOUND2, and KJFS it verifies:

- valid import/export and relocation parsing;
- measured module name, image size, entry offset, and GP offset;
- a representative live guest export within the loaded image;
- successful reverse-order unload;
- removal of every representative export after unload; and
- identical allocator bases when the entire load/unload sequence is repeated.

The contract separately loads the exact encrypted `libfont.prx` identity
through its HLE policy, unloads it, and proves that both a one-byte hash
mismatch and the exact bytes under an unknown path fail with
`0x80020148`. The first-mission smoke route independently requires
`libfont.prx` to be the only encrypted HLE module requested before its
checkpoint.

The route's structured log is filtered to module, thread, and fatal events.
Its lifecycle validator rejects failed loads/unloads, unknown unload UIDs,
identity changes, active image overlap, missing first-mission load, missing
reuse of either observed stage base, and drift in the exact plaintext-module
start/worker sequence. Together with the successful mission frame, this guards
the currently observed interpreted overlay replacement path. The separate
callback-stop probe is recorded in MGSPO-F-017.

## MGSPO-F-016 - Profile-guided native ZLIB promotion

**Status:** Confirmed

The presentation-7,000 turbo profile originally attributed 329,115,603 of
542,982,455 interpreted instructions to exact module `ZLIB`, versus
205,850,823 to SOUND2 and 5,810,160 to the first mission overlay. This made
ZLIB the first evidence-backed promotion candidate.

Pinned generation produced 118/118 functions, zero trapping stubs, two code
chunks, and one registration unit at the measured route base `0x08b20000`.
With native ZLIB, the same accelerated route reported 79,528,687 interpreted
instructions, no interpreted ZLIB target, and 35.39 seconds elapsed versus
45.171 seconds before promotion. That is an 85.4% reduction in interpreted
instructions and a 21.7% host-time reduction on that profiling route.

The promotion remains exact-identity and exact-base gated. Validation includes:

- both executable contracts;
- a 100,000-step trace matching the pinned PPSSPP oracle;
- five consecutive paced clean-profile mission runs;
- the same mission identity, six unloads, base reuse, savedata, and exact
  pause-region hash on every run; and
- zero interpreted ZLIB entries in every promoted-run profile.

Native ZLIB is therefore the production default. `--interpreted-zlib` remains
available in the smoke tool for direct comparison. This promotion does not
close the separate ZLIB output/error-semantics task.

## MGSPO-F-017 - Plaintext lifecycle callbacks are exact

**Status:** Confirmed

The pinned PPSSPP event and CPU traces expose the complete boot-time start
sequence:

- ZLIB UID `0x11b` starts callback `0x08b216b4` on thread `0x11c`, with
  priority `0x20`, a `0x40000`-byte stack at `0x09fc0000`, GP `0x08b2c090`,
  zero arguments, SP `0x09fffec0`, K0 `0x09ffff00`, and return stub
  `0x08000030`; it exits with status zero.
- SOUND2 UID `0x11e` has the no-entry sentinel and starts without creating a
  callback thread.
- KJFS UID `0x120` starts callback `0x08b77ae8` on thread `0x121` with the same
  priority, stack geometry, argument state, and return stub plus GP
  `0x08b8b9e0`. It creates dormant workers `preseek` UID `0x122`, entry
  `0x08b779d0`, priority `0x11`, stack `0x2000`, and `dbr` UID `0x125`, entry
  `0x08b7711c`, priority `0x12`, stack `0x1800`, then exits with status zero.

Structured runtime records now include callback addresses, effective
priority/stack/attributes, GP, arguments, reset SP/K0/RA, and exit status. The
clean-save verifier requires this entire ordered start sequence before
accepting the first-mission checkpoint.

The exact PRXs export ZLIB stop callback `0x08b216bc`, no SOUND2 stop callback,
and KJFS stop callback `0x08b77c24`. The project stop path follows the pinned
PPSSPP contract: it runs valid callbacks on dedicated module threads, returns
the callback result through the status pointer, resumes the caller with zero,
handles the no-callback case without a thread, and rejects an already-stopped
module with `0x80020135`. A gated probe stops KJFS, SOUND2, then ZLIB and
requires callback threads `0x127` and `0x128`, reused stack
`0x09fc0000-0x0a000000`, exact GP/reset state, and zero exit status. The probe
passes with both generated-native and interpreted ZLIB. Enabling this path
does not perturb the normal boot oracle: the current 100,000-step trace remains
an exact match.

## MGSPO-F-018 - KJFS service comparison

**Status:** Partial

An opt-in probe invokes exports only after the exact `KCEJ_FS` module is
loaded at its measured base. Calls use PSP EABI argument registers, including
`t0` for the fifth argument. Pinned PPSSPP interpreter captures and the
standalone runtime agree on 20 probe calls in both generated-native and
interpreted ZLIB modes, using either ISO-backed files or the extracted tree.
The comparison checks case order, argument values and exact path bytes, return
values, both halves of 64-bit seek results, complete read buffers, and
unchanged 16-byte guards.

For the 48-byte direct disc file, PPSSPP returned 49 for an absolute seek
beyond EOF and 51 for a subsequent current-relative seek of two bytes. The
standalone previously clamped both positions to 48. Byte-mode disc seeks now
preserve supported positions beyond EOF, and subsequent reads return zero
without underflowing the remaining-byte count. Byte-mode asynchronous
operations use the same project-owned read/seek behavior. The executable
contract and the normally paced first-mission smoke route pass after this
change.

PPSSPP also opens and closes `disc0:/./UMD_DATA.BIN` and
`disc0://UMD_DATA.BIN` successfully. The standalone previously retried the
first path indefinitely. Disc lookup and directory listing now remove
single-dot components before resolving both the ISO and the extracted tree;
four open/close cases match PPSSPP in both ZLIB modes and both mount modes.
Parent components remain rejected by the existing disc lookup.

The original canonical-file case requested eight bytes, received
`0xffffffff`, and observed all 59 bytes written inside the guarded 64-byte
buffer. Natural title evidence resolves this apparent contradiction: the
caller first queries size 59, passes 59 to the read export, ignores its return
value, advances by the queried size, and closes the handle. The return is
therefore a title-observed completion sentinel for this transfer, not an
ordinary failure code, and the original eight-byte case did not model a
bounded eight-byte read.

The `kjfs-v4` probe appends that natural open/size/read/close sequence. PPSSPP
and both standalone ZLIB modes agree on handle 3, size and read count 59, the
exact nonempty `data.cnf` payload, an untouched five-byte buffer suffix and
both 16-byte guards, read result `0xffffffff`, and close result zero. The
oracle derives the read count from the preceding size result and independently
rejects an empty transfer, residual sentinels, or writes beyond that result.

The Acid projects' fail-closed `_zar` resource parser supplied the missing
archive-versus-file distinction. The verified ISO has no physical
`stage/init/data.cnf`; its physical directory contains `_zar` and `init.prx`.
The local `_zar` resource decompresses to five indexed entries, including the
59-byte `data.cnf` with SHA-256
`147ad2ea27a599af54da18e2875ff337c2df7fbdc4283d89ae26a1ab69517120`.
Every `kjfs-v4` manifest now records and verifies the `_zar` path, size and
SHA-256, the entry path, name, size and SHA-256, and the absence of a physical
ISO file before running either implementation.

This proves a successful nonempty KJFS archive-entry read from `_zar`. It does
not yet prove an entry lookup inside the nested `cache.qar` or `cache.dar`
containers. Additional isolated ranges match PPSSPP in both ZLIB modes for:

- a dotted parent-component path returning `0xffffffff`, followed by close
  result zero;
- a missing entry open returning handle 3, which is not independently treated
  as success without a subsequent size/read;
- a null destination read returning `0xffffffff`, followed by close result
  zero; and
- an open followed by count-zero and count-64 reads. The count-zero call still
  writes the complete 59-byte entry, and the second call advances internal
  state and writes a different exact 64-byte buffer. Both external guards
  remain unchanged.

These results further prove that the third read argument is not a conventional
bounded byte count in this archive mode. A completed 10,000,000-step natural
event-only PPSSPP capture sees KJFS open the `_zar` entries, `cache.qar`,
`cache.dar`, and the next stage's `resident.qar`; no observed KJFS export
receives the inner QAR names. Nested QAR/DAR parsing is therefore tracked as a
separate title-side consumer rather than an invented KJFS entry API.

The remaining exported calls intentionally do not return. Instruction-limit
termination was not accepted as evidence. The `kjfs-v5-blocked` oracle instead
observes syscall returns, requires eight exact retry cycles on one guest
thread, writes a `kjfs_probe_blocked` event and `service.blocked` marker, and
stops both producers normally. Any wrong NID, PC, result, delay, thread,
asynchronous result, exported-call return, timeout, crash, or missing marker
fails the capture. PPSSPP and both standalone ZLIB modes agree on:

- stages 20 and 28: `sceIoOpen` at `0x08b761b8` returns `0x80010002`, then
  `sceKernelDelayThreadCB` at `0x08b761dc` delays 1,000,000 microseconds;
- stage 31: the archive worker's `sceIoRead` at `0x08b77cb0` returns
  `0x80020323`, then its delay at `0x08b77cc4` uses 1,000,000 microseconds;
- stage 43: `sceIoLseekAsync` at `0x08b763c4` returns zero,
  `sceIoWaitAsyncCB` at `0x08b763d4` returns zero and completes with both
  32-bit result halves equal to `0xffffffff`, then the delay at `0x08b76414`
  uses 1,000,000 microseconds; and
- stage 45: the same asynchronous seek returns `0x80020323` without a wait,
  then delays at `0x08b76414`.

The mode-zero case exposed a real standalone discrepancy. PPSSPP permits the
descriptor to open but records its access mode, so the archive worker's read
fails with `SCE_KERNEL_ERROR_BADF`. The standalone runtime previously omitted
descriptor access bits, returned the complete 34,779-byte `_zar` resource, and
allowed the KJFS export to finish. Project-owned descriptor access tracking
now rejects synchronous and asynchronous reads without read access while
leaving the offset and destination unchanged. The production executable
contract covers this behavior without modifying the pinned `psp-recomp`
checkout.

PPSSPP callback waits reschedule before the outer HLE dispatcher regains
control. The oracle therefore preserves each return value before rescheduling
and validates the asynchronous 64-bit seek result when the same guest thread
reaches its following delay. This distinguishes actual callback completion
from an immediate HLE dispatch return.

These captures close the non-returning normalization, invalid-seek, and
asynchronous-completion portion of the KJFS gate. The separate title-side
QAR/DAR consumer and the ZLIB and SOUND2 service gates remain open.

## MGSPO-F-019 - Experimental GPU and paced performance diagnostics

**Status:** Partial

The [Acid 1 performance reporter](https://github.com/Tzeentchnet/MetalGearAcid-Recomp/blob/master/tools/mga/perf_report.py)
and [Acid 2 performance ledger](https://github.com/Tzeentchnet/MetalGearAcid2-Recomp/blob/main/docs/ARENA_PERFORMANCE.md)
informed the profiling approach. Acid 2 uses this project's pinned
`psp-recomp` revision; Acid 1 uses a different revision. Measurements from
either title are not Portable Ops performance claims.

The normal build remains software-only. The separate experimental D3D12
preset builds the pinned toolkit backend with SDL3 3.2.20 when the pinned
package must be fetched. Its framebuffer write barrier uses the pinned
backend's full-target readback only for GPU-newer targets overlapping a CPU
write. The earlier partial readback left the rest of a target GPU-newer while
the subsequent CPU write invalidated the entire target. A first, interrupted
hardware diagnostic logged 43 such invalidations; three subsequent routes
logged none. A targeted unit test covers target selection, synthetic
partial-write preservation, and readback failure. This does not establish
complete coherency for other workloads.

The automated pause check previously used individual guest reads for every
pixel, each potentially triggering a GPU readback. It now synchronizes VRAM
once before the pixel scan. In a bounded, non-acceptance comparison near
presentations 6,903-7,015, the interrupted pre-fix run recorded 652,800
readbacks and 4,022 ms p95 over 59 host-flip intervals; the later run recorded
four readbacks and 33.37 ms p95 over 51 intervals. Bounds, workloads, and
diagnostic logging differed, so these numbers demonstrate the scan issue,
not a validated gameplay speedup. The later whole route still reported
391,751 framebuffer readbacks. A subsequent whole-route trace attributed
391,686 of the same total to three CPU presentation fallbacks ending at
presentation counts 1,676, 1,726, and 5,245. Each converted all 130,560
visible `480x272` pixels and triggered 130,562 readbacks. The overlapping
GPU-newer targets belonged to earlier capture generations, not the current
unsubmitted command list.

The project wrapper now records each failed cached-presentation lookup and,
on the first matching CPU pixel read, fully reads back overlapping older-
generation targets once. It refuses to batch if any overlapping GPU-newer
target is written or state-transitioned by the current command list. A
read-only texture reference already in pixel-shader-resource state is safe:
the immediate readback completes first and restores that state before the
current list executes. A targeted test covers older-generation batching,
current-command-list refusal, and readback failure.
In a like-configured traced route, total readbacks fell from 391,751 to 71.
The three intervals fell from 130,562 to two readbacks each; synchronization
fell from 10,152, 9,415, and 6,878 ms to 4.61, 4.66, and 4.28 ms. Route wall
time fell from 101.75 to 76.55 seconds, although paced route timing and host
flip counts differed and this is not a guest-FPS acceptance result. No
current-generation refusal or newer-framebuffer invalidation occurred.
The optional D3D12 debug-layer run could not start because
`D3D12GetDebugInterface` returned `0x887a002d`; Windows Graphics Tools is not
installed on the reference system, so debug-layer state validation remains
open.

On Windows 11 build 26200, Ryzen 7 9800X3D, RTX 5070 driver
`32.0.16.1742`, and clang-cl 19.1.5, normally paced native-ZLIB profiles
covered the active mission before the pause request. In the
6,901-6,999 presentation-count range, the software run recorded 39 host-flip
intervals with 37.40 ms mean, 62.29 ms p95, and 27.92 ms mean in the
aggregate vertex/primitive category. The D3D12 run at native 1x resolution,
1x texture scaling, anti-aliasing off, and full-rate shading recorded 45
intervals with 21.91 ms mean, 33.37 ms p95, and 4.92 ms mean in that
category. Their draw counts and repeated presentation counts differ, and
D3D12 stage/vertex/framebuffer logging was enabled; these are diagnostic
samples, not matched-workload or guest-FPS acceptance results.

On the same system, a second resolution sweep disabled stage, vertex,
framebuffer, and read-trace logging and used full-rate shading. Two normally
paced runs at each scale measured the requested presentation-count interval
6,901-6,999. Delayed GPU samples were aligned to their source flips and
normalized by the sampled draw workload:

| Internal resolution | Visible size | Mean paced frame time, run range | Mean active GPU time, run range | Active GPU p95 range | GPU ms / 1,000 draws |
|---|---:|---:|---:|---:|---:|
| 1x | 480x272 | 19.42 ms (19.12-19.73) | 1.246 ms (1.232-1.261) | 1.277-1.373 ms | 0.794 |
| 2x | 960x544 | 21.05 ms (20.59-21.52) | 1.832 ms (1.825-1.840) | 1.865-1.882 ms | 1.161 |
| 4x | 1920x1088 | 19.62 ms (19.32-19.91) | 3.305 ms (3.304-3.305) | 3.321-3.369 ms | 2.098 |

Relative to 1x, active GPU time increased 1.47x at 2x and 2.65x at 4x.
All six captures had frame-time p99 near 33.37 ms and no frame above
34.05 ms in the bounded interval. The non-monotonic paced frame means and host
flip rates are dominated by scheduler/VSync behavior and slightly different
host-flip sampling; they are not evidence that 4x is faster than 2x. The
active GPU metric is stable across repeats and remains well below the
33.33 ms frame budget on this RTX 5070. No framebuffer readbacks, texture
misses, texture-decode waits, or PSO fallbacks occurred inside the selected
interval.

The scale sweep also found a visual boundary. Both 1x runs reproduced the
accepted 65,280-pixel stable-region hash. The two 2x runs repeated hash
`cd5251127a54ef2de7db3a196e9cedef463cdb59b0b1ed5b703d77fbc965d16c`;
23,908 pixels (36.62%) differed from 1x, with mean absolute channel
difference 8.316 and maximum 173. The two 4x runs repeated hash
`f04a4b3b531c88d23429ebf6fd838edf728f850772704db93c5df0ae0afe2773`;
21,700 pixels (33.24%) differed, with mean absolute channel difference 4.612
and maximum 107. These repeatable higher-resolution hashes are diagnostic
identities, not approved correctness references. The 2x and 4x modes therefore
remain outside the current exact software checkpoint even though their
performance headroom is ample on this hardware.

An earlier hardware run recorded 30,893,256 captured vertices and 259,895
batches over the complete route, including direct and manual GPU draws.
Delayed GPU times are associated with their source flips by `perf_report.py`.
Missing backend timing is reported as unavailable rather than zero. Host flips
and framebuffer-call counts are not verified guest-visible frames.

Both renderers reached the first-mission pause. Four D3D12 runs using the
toolkit's default integer-quantized texture path produced the same hardware
region hash, including the batched-readback run. Comparison against the
software capture found 22 different pixels, all by at most nine RGB levels.
The hardware value was lower in all three channels at each changed pixel:
17 pixels by nine levels and five by eight. Forcing every draw through the
manual destination-aware shader produced an identical capture and ruled out
the direct fixed-function path.

Setting `SR_GPU_PSP_SAMPLER=0` selected the hardware texture path and changed
all 22 pixels to the exact software values. The experimental executable now
applies that title-specific setting when the variable is absent, before
renderer initialization, while preserving `SR_GPU_PSP_SAMPLER=1` as an A/B
override. A fresh default-on route matched all 65,280 pixels in the stable
`240x272` region, reproduced SHA-256
`39751fb212b51863b6d2dbb2d4c1861e022cf4c6c983573998c161ff14ad0ae3`,
and retained 70-71 framebuffer readbacks across the default and concurrent
stress routes. The toolkit flag controls both texture sampling and
texture-combine arithmetic, so this bisect does not yet isolate which
sub-operation caused the 22 adjacent 5-bit-level results. The other half
contains an animated map and was not phase-aligned.

No PPSSPP reference frame or accepted tolerance exists, so the broader D3D12
visual gate and 30 FPS remain unsigned off. XAudio2 initialized but reported
substantial resynchronization; audible output and timing remain separate open
gates.

## MGSPO-F-020 - Settings and local source installation boundary

**Status:** Implemented with restart boundary

The pinned runtime already supplied typed `graphics.ini` and `input.ini`
parsers, atomic replacement, first-run graphics/controller dialogs, and a
four-Hz input file watcher. Portable Ops now exposes those facilities through
standalone `--configure` and `--configure-input` modes and a project-owned F1
settings hub. The hub is called between guest dispatches, so the cooperative
guest scheduler is paused while its modal windows are open.

The project-owned remapper covers all 12 PSP actions for keyboard, mouse, and
controller input plus four keyboard analog directions. It retains editable
comma-separated values for up to four bindings, captures supported keyboard
and mouse controls directly, and polls XInput buttons/triggers in a bounded
modal capture window. Dead zones, response curves, inversion, and twin-stick
settings share the same validated `SrInputConfig`. A successful atomic save
updates the active runtime configuration immediately; invalid values leave the
previous configuration active. DirectInput-only press capture remains open,
although its named bindings are still editable.

Graphics settings are intentionally restart-only. The active graphics
configuration is snapshotted after renderer initialization. Saving renderer,
internal-resolution, texture-scale, shading-rate, SMAA, or startup changes
marks the hub restart-required when the saved values differ from that
snapshot. **Restart Now** starts the same executable with the inherited
environment and exits the old process. No unsafe live D3D12 target/cache
teardown is attempted.

The Python/Tkinter manager is a source-user bootstrap, not a redistributable
installer. It locates a sanitized Visual Studio developer environment, checks
Git/CMake/Ninja/clang-cl, verifies the exact ISO size and SHA-1, and invokes
the existing extraction and generation tools before the selected configure,
build, and CMake install steps. Its ignored state stores paths only. CMake
stages the executable, user-derived generated image, fonts, VFPU tables,
project documents, and SDL3 for D3D12; it never stages the ISO.

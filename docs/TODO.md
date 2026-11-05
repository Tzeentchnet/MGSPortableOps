# TODO - First Playable at 30 FPS

## Goal

Deliver a source-only Windows build for ULUS-10202 v1.00 that:

- boots from a clean launch to the title/menu flow;
- accepts controller and keyboard input in menus;
- starts a new game and enters the first playable mission;
- remains playable for at least 10 minutes with working player control,
  camera, HUD, collision, AI, scripting, audio, and pause/resume; and
- sustains a correctly paced 30 FPS on documented reference hardware.

The frame-rate goal is guest-visible 30 FPS, not merely 30 host presentation
calls per second. Simulation, input, audio, and cutscene timing must remain
correct.

## Definition of done

- [ ] A clean clone plus the supported user-supplied ISO can extract, generate,
      build, and launch without manual file copying.
- [x] Five consecutive clean launches reach an interactive main menu.
- [x] Five consecutive new-game runs enter the first playable mission.
- [ ] Three 10-minute mission runs complete without a crash, hang, trapping
      stub, unknown encrypted-module fallback, or unrecoverable desync.
- [ ] A Release build passes the 30 FPS acceptance test defined below.
- [x] No game data, generated game C, traces, captures, saves, or build products
      are tracked by Git.
- [x] The measured boot contract, validation procedure, known limitations, and
      reproduction commands are documented before declaring the milestone.

## Guardrails

- Measure title state from a pinned PPSSPP interpreter build. Do not copy boot
  constants from another title or recompilation.
- Keep module handling fail-closed. Every encrypted-module policy must match an
  exact measured identity.
- Validate the software renderer first, then compare the hardware renderer
  against the same reference points.
- Fix correctness before optimizing. Profile before changing architecture or
  promoting interpreted modules to native code.
- Keep private evidence under ignored build/output directories.

## Current baseline

- [x] Verify the ULUS-10202 ISO and required executable hashes.
- [x] Inventory 25 service/module PRXs and 106 stage PRXs.
- [x] Measure the main executable layout, imports, entry point, and GP.
- [x] Generate all 19,671 accepted main-module functions with zero trapping
      stubs.
- [x] Generate all 118 accepted ZLIB functions with zero trapping stubs and
      activate them only for the exact measured module identity and base.
- [x] Compile all generated translation units with clang-cl in Release mode.
- [x] Pin and verify the `psp-recomp` runtime revision.
- [x] Build a standalone executable.
- [x] Execute the first correctly initialized guest instruction.
- [x] Reach the first visible frame.

See [STATUS.md](STATUS.md) and [FINDINGS.md](FINDINGS.md) for the proven
boundary.

## Current focus

Work proceeds in this order:

1. Validate the title-side QAR/DAR consumers, ZLIB output and errors, and
   SOUND2 streaming and synchronization against PPSSPP.
2. Capture matching PPSSPP software-renderer frames and define objective
   pixel-difference tolerances.
3. Extend the deterministic mission route through camera, combat, items,
   interactions, radio, AI, damage, pause/resume, and restart.
4. Complete three deterministic 10-minute mission runs.
5. Validate D3D12 against the software and PPSSPP checkpoints.
6. Profile the measured route and meet the documented 30 FPS thresholds.

## Milestone 1 - Capture the boot oracle

- [x] Select and record an exact PPSSPP revision, build configuration, compiler,
      and runtime settings.
- [x] Add or maintain a private PPSSPP trace patch that records:
  - [x] module-start UID, next UID, and initial GE list ID;
  - [x] entry PC, GP, SP, argument registers, and all other GPR state;
  - [x] thread priority, stack size, attributes, and scheduler state;
  - [x] kernel-prepared argument strings and memory;
  - [x] relevant memory-map and module allocation state; and
  - [x] instructions, register deltas, memory writes, imports, syscalls, and
        thread transitions for a fixed bounded window.
- [x] Capture the oracle from an interpreter-only run of the supported disc.
- [x] Repeat the capture and prove the initial state and bounded trace are
      deterministic.
- [x] Record the verified start-thread values in `config/mgspo.toml`.
- [x] Store the PPSSPP revision and trace-format version with every private
      capture.

Exit gate:

- [x] The initial machine state is independently measured and reproducible.
- [x] A trace comparator reports the first mismatch with enough register and
      memory context to diagnose it.

## Milestone 2 - Add the standalone runtime

- [x] Add a standalone executable target only after
      `module.start_thread.verified` is true.
- [x] Initialize the PSP memory map and load the relocated main image.
- [x] Reproduce the measured UID, thread, scheduler, stack, argument, register,
      and GE state.
- [x] Register the generated native main-module functions.
- [x] Register strict title module policies before guest execution begins.
- [x] Mount the extracted private disc tree with the title's expected path and
      case behavior.
- [x] Implement the host loop for guest scheduling, display timing, input,
      audio, and orderly shutdown.
- [x] Add structured logs for module loads, imports, syscalls, threads, display
      lists, file failures, and fatal errors.
- [x] Emit a useful crash report containing the guest PC, registers, current
      thread, loaded modules, and recent guest events.
- [x] Add a deterministic headless command suitable for automated smoke tests.

Exit gate:

- [x] Native execution matches the PPSSPP oracle for the bounded trace.
- [x] The executable reaches a stable, named headless boot checkpoint on five
      consecutive runs.

## Milestone 3 - Make the module and I/O path reliable

- [x] Exercise `kjfs.prx` through interpreter fallback using its exact hash.
- [x] Exercise `zlibdec.prx` through interpreter fallback using its exact hash.
- [x] Exercise `sound2.prx` through interpreter fallback using its exact hash.
- [x] Verify exact hashes, imports, relocations, GP setup, exports, load/unload,
      allocator reuse, and stale-export removal for each plaintext module.
- [x] Verify lifecycle callbacks and thread creation for each plaintext module.
- [x] Verify stage PRX loading at runtime-selected bases.
- [x] Verify address reuse when one stage overlay replaces another.
- [x] Prevent stale native/interpreter mappings after overlay unload.
- [x] Inventory every encrypted module requested before the menu and first
      mission.
- [x] Add only exact-identity HLE policies for encrypted modules that are
      actually required.
- [x] Make unknown or mismatched encrypted modules fail with an actionable
      error.
- [ ] Validate KJFS archive access, path normalization, seek/read behavior, and
      end-of-file semantics against PPSSPP.
  - [x] Compare 20 bounded archive and direct-file calls, including guarded
        read buffers and direct-file EOF/seek cases, in native and interpreted
        ZLIB modes.
  - [x] Compare direct-file open/close with `.` and repeated separators on
        ISO-backed and extracted-tree mounts.
  - [x] Prove the natural size-driven 59-byte `data.cnf` archive-entry transfer
        from `stage/init/_zar`, including its exact payload, untouched guards,
        and title-observed `0xffffffff` completion sentinel, in both ZLIB modes.
  - [x] Compare dotted and missing archive-entry paths, a null destination, and
        consecutive zero/64-count reads with guarded buffers in both ZLIB modes.
  - [x] Prove the non-returning uppercase-device, repeated-separator,
        mode-zero, negative-seek, and invalid-handle-seek cases with eight
        exact syscall retry cycles, including asynchronous completion, in
        both ZLIB modes; reject timeouts and missing completion markers.
  - [ ] Validate the title-side QAR/DAR consumers.
- [ ] Validate ZLIB decompression output and error behavior against PPSSPP.
- [ ] Validate SOUND2 streaming, buffering, thread synchronization, and timing.
- [x] Profile interpreted module hotspots and promote a module to generated
      native code only when evidence justifies it.

Exit gate:

- [ ] All modules needed through first-mission entry load and unload without
      traps, permissive fake success, or stale overlay state.

## Milestone 4 - Reach and validate visible output

- [x] Reach the first display list and framebuffer presentation.
- [ ] Capture private PPSSPP reference frames at:
  - [ ] first visible frame;
  - [ ] publisher/logo screens;
  - [ ] title screen;
  - [ ] main menu;
  - [ ] mission loading; and
  - [ ] first controllable mission frame.
- [ ] Reproduce those checkpoints with the software renderer.
- [ ] Compare dimensions, framebuffer format, viewport, scissor, clear values,
      depth/stencil behavior, blending, alpha test, fog, texture sampling,
      CLUTs, and render-to-texture behavior.
- [x] Add an exact PPM frame-difference report without assuming a tolerance.
- [ ] Define a pixel-diff tolerance and document every intentional difference.
- [ ] Verify framebuffer readback and CPU/GPU coherency only where the guest
      requires them.
- [x] Add an isolated, experimental D3D12 build and a checked write barrier for
      GPU-newer framebuffers.
- [ ] Enable D3D12 after the software references pass.
- [ ] Validate D3D12 output against the same checkpoints.
- [x] Match the deterministic `240x272` first-mission pause region exactly
      against the production software renderer without a tolerance.
- [ ] Ensure the hardware path does not also run a complete CPU render pass.
- [ ] Remove avoidable synchronous uploads, readbacks, and per-frame GPU waits.
- [x] Trace the three large early readback bursts and, if they come from the
      CPU presentation fallback, batch them without crossing unsubmitted GPU
      work or losing framebuffer coherency.
- [ ] Cache pipelines and shaders without hiding compilation failures.

Exit gate:

- [ ] The menu and first mission render correctly through D3D12 with no known
      progression-blocking graphics defect.

## Milestone 5 - Make the menu flow interactive

- [x] Map PSP buttons, analog input, and configurable dead zones.
- [ ] Validate menu key/button repeat behavior against PPSSPP.
- [x] Support at least one XInput controller and a documented keyboard layout.
- [ ] Handle controller disconnect/reconnect without hanging guest input.
- [ ] Match PPSSPP input sampling and frame pacing closely enough for menus and
      gameplay.
- [x] Play intro/video content or implement a documented, deterministic skip
      path if media support is not ready.
- [ ] Validate menu music, sound effects, and audio/video synchronization.
- [x] Implement the savedata operations required to create a clean profile.
- [ ] Validate cancellation, overwrite, missing-save, and storage-error paths.
- [x] Create a repeatable input script from process launch to the new-game
      confirmation.
- [x] Run that path from a clean save five consecutive times.

Exit gate:

- [ ] The title screen and main menu are visually correct and responsive.
- [x] A clean user can select New Game and begin loading the first mission.

## Milestone 6 - Enter and play the first mission

- [ ] Trace and validate the first mission's archive reads and decompression.
- [x] Load the required stage overlay and verify its exact identity and base.
- [ ] Validate mission script startup and required worker threads.
- [x] Reach the first player-controllable frame without debug-only intervention.
- [ ] Verify:
  - [x] forward analog movement and running animation;
  - [ ] analog speed, dead zones, and partial deflection;
  - [ ] camera control and recentering;
  - [ ] aiming, attacks, weapon/item selection, and basic CQC;
  - [x] collision with the prison-cell bed;
  - [ ] gravity, doors, ladders, and interaction prompts used by the test
        route;
  - [x] HUD and radar output;
  - [x] pause-menu entry;
  - [ ] text, pause/resume, and mission radio used by the route;
  - [ ] enemy spawning, navigation, perception, alerts, and damage;
  - [ ] mission scripting, triggers, checkpoints, and failure/restart;
  - [ ] music, voices, effects, and streaming synchronization; and
  - [ ] return to gameplay after pause or radio transitions.
- [ ] Define a deterministic 10-minute first-mission test route.
- [ ] Capture a synchronized PPSSPP reference run for that route.
- [ ] Compare major event order, visible state, and audio timing.
- [ ] Complete the route three times without a crash, hang, or progression
      blocker.

Exit gate:

- [ ] The first mission is meaningfully playable for at least 10 minutes.

## Milestone 7 - Establish correct 30 FPS behavior

- [ ] Measure the title's original guest update, render, audio, and timer rates.
- [ ] Determine whether the unmodified title targets 30 FPS.
- [ ] If a title patch is required, isolate and document it:
  - [ ] preserve real-time simulation speed;
  - [ ] preserve input sensitivity and animation speed;
  - [ ] preserve audio pitch and synchronization;
  - [ ] preserve cutscene and scripted-event timing; and
  - [ ] make the patch independently toggleable for comparison.
- [ ] Add per-frame CPU and GPU timing with categories for:
  - [ ] translated main-module execution;
  - [ ] interpreted and native dynamic modules;
  - [ ] HLE/syscalls and scheduler work;
  - [ ] KJFS, decompression, and streaming I/O;
  - [ ] GE decode and renderer submission;
  - [ ] GPU execution, fences, uploads, and readbacks; and
  - [ ] audio mixing and synchronization.
- [x] Add a diagnostic report that separates host flips from guest presentation
      changes and aligns delayed GPU samples.
- [x] Compare two normally paced D3D12 captures at 1x, 2x, and 4x internal
      resolution over the same bounded first-mission interval; retain
      workload-normalized GPU timings and scale-specific visual hashes.
- [ ] Capture profiles on the deterministic 10-minute route.
- [ ] Rank bottlenecks by frame-budget contribution.
- [ ] Optimize only measured bottlenecks and retain before/after captures.
- [ ] Keep guest CPU, GPU submission, GPU execution, and audio work overlapped
      where dependencies allow.
- [ ] Verify Release builds do not enable trace, validation, or software-render
      work during the performance run.

### 30 FPS acceptance test

- [ ] Document CPU, GPU, RAM, OS version, driver, resolution, renderer, VSync
      mode, compiler, commit, save state, and exact mission route.
- [ ] Warm shader/pipeline caches with one complete run.
- [ ] Record the next 10-minute run from first player control; report loading
      transitions separately.
- [ ] Cap presentation at 30 FPS and verify one guest-visible frame per intended
      presentation interval.
- [ ] Achieve all of:
  - [ ] average frame rate at or above 29.7 FPS;
  - [ ] 1% low at or above 27 FPS;
  - [ ] at least 99% of gameplay frames at or below 40 ms;
  - [ ] no recurring gameplay hitch above 100 ms; and
  - [ ] correct simulation, input, animation, cutscene, and audio timing.
- [ ] Repeat the benchmark three times and retain the reports privately.

Exit gate:

- [ ] The first mission meets the acceptance thresholds on documented
      reference hardware without correctness regressions.

## Milestone 8 - Reproducibility and milestone sign-off

- [x] Add automated tests for the measured boot-state parser and trace
      comparator.
- [x] Add a smoke test for the bounded headless boot checkpoint.
- [ ] Add smoke tests for the first frame and menu checkpoint.
- [x] Add a clean-save first-mission entry smoke test.
- [x] Add a framebuffer-hash test for the stable first-mission checkpoint.
- [ ] Add framebuffer-hash tests for the earlier stable checkpoints.
- [x] Add module lifecycle and address-reuse regression tests.
- [x] Run all 119 Python tests, generation validation, production and D3D12
      Release builds, both executable contracts, the source-install manager
      workflow, and the deterministic first-mission smoke route in the current
      checkout.
- [ ] Run source tests, generation validation, full Release build, and runtime
      smoke tests from a clean clone.
- [x] Verify all private/generated artifacts remain ignored.
- [x] Update `../README.md`, `STATUS.md`, `FINDINGS.md`, `REPRODUCTION.md`,
      and `ADVANCED_INSTALLATION.md` with measured commands and results.
- [x] Keep this authoritative task list under `docs/` and link it from the
      root README and status page.
- [x] Record known correctness and performance limitations.
- [ ] Tag the first-playable milestone only after every definition-of-done item
      passes.

## Cross-cutting usability - settings and local installation

- [x] Add `--configure` and `--configure-input` entry points to reopen native
      settings without starting the game.
- [x] Add an F1 runtime settings hub that pauses guest execution.
- [x] Apply keyboard, mouse, controller, dead-zone, curve, inversion, and
      twin-stick changes immediately through the existing atomic input config.
- [x] Add keyboard, mouse, and XInput capture to the native remapper while
      retaining editable multi-binding values.
- [x] Save graphics changes and offer an explicit restart when they differ
      from the active renderer configuration.
- [x] Add a Python/Tkinter source-install manager for dependency checks, exact
      ISO verification, extraction, generation, configure/build/install, native
      control configuration, graphics settings, and launch.
- [x] Add CMake install staging for the executable, private generated image,
      fonts, VFPU assets, project documents, and optional SDL3 runtime.
- [ ] Add live renderer/resource recreation only after target materialization,
      cache invalidation, failure rollback, and D3D12/software parity are
      proven.
- [ ] Add runtime audio volume/mute and device selection after audio playback
      and synchronization pass their correctness gates.
- [ ] Add capture for DirectInput-only controllers; named bindings and XInput
      capture are available now.
- [ ] Add release packaging only after the first-playable acceptance gates;
      never package or redistribute user-supplied game data.

## Deferred until after first playable

- Full-campaign compatibility and regression coverage.
- Multiplayer and network services.
- PAL/Japanese/revision support.
- Widescreen, high-resolution assets, texture replacement, or visual mods.
- Uncapped frame rates above 30 FPS.
- Release-installer polish, automatic updating, and achievements.

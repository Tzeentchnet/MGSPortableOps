# Status

## Current milestone

Phase 1: exact-disc survey and static-translation bootstrap.

Completed:

- source-only repository and exclusions;
- exact `psp-recomp` submodule pin;
- strict ULUS-10202 ISO and required-file verification;
- inventory of 25 module PRXs and 106 stage PRXs;
- independently measured main-module layout;
- complete main-module code generation with zero trapping stubs; and
- clang-cl Release compilation of all generated translation units.

## Validation boundary

The current build proves that the supported main executable can be relocated,
analyzed, translated, and compiled against the pinned runtime headers. It does
not prove that the title starts with correct kernel state or reaches a visible
frame.

The standalone driver is intentionally absent until the following values are
captured from a fixed PPSSPP interpreter build:

- module-start UID, priority, stack size, and attributes;
- next kernel UID and initial GE list ID;
- initial argument string and register state;
- GP and stack behavior at the real module entry; and
- any kernel-prepared memory required before the first instruction.

## Next gates

1. Pin a PPSSPP revision and capture the module-start oracle.
2. Add a differential trace for an initial bounded instruction window.
3. Build the standalone runtime only after that trace matches.
4. Validate KJFS, ZLIBDEC, and SOUND2 through interpreter fallback first.
5. Add an exact HLE policy for each encrypted module actually requested.
6. Reach a deterministic headless boot checkpoint.
7. Establish software-renderer reference captures.
8. Enable and validate the D3D12 path against those captures.

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

## MGSPO-F-007 - Boot contract remains unknown

**Status:** Open

The executable layout is measured, but the module-start UID state, scheduler
state, argument memory, and initial GE list ID have not been independently
captured. Values from another title or recompilation must not be copied as a
substitute.

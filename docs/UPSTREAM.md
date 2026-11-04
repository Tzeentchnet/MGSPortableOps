# Shared `psp-recomp` opportunities

## Analyzer alignment invariant

Function entries must be four-byte aligned. Candidate pointers discovered in
module metadata, export tables, or data should be filtered through the same
alignment-aware executable-range predicate used for ordinary text pointers.

A synthetic regression should include an import NID whose numeric value falls
inside the executable range but is unaligned.

## Absolute jumps within a function

The analyzer currently treats every absolute `j` target as a function call.
Portable Ops contains a backward absolute jump from `0x08902050` to its own
epilogue at `0x08901fe4`. Promoting that target and nearby delay/fallthrough
labels creates duplicate false functions.

A generic fix needs to distinguish an intra-function epilogue jump from a tail
call without reducing real tail-call discovery. Until that is proven with a
synthetic fixture, the title wrapper excludes the exact observed addresses.

## Generated-label validation

Split generation should fail before compilation when a generated function
contains a `goto` to a local label that was not emitted. The title generator
implements this check; moving an equivalent structural validation into the
shared code generator would give every title an earlier, clearer failure.

## Upstreaming rule

These are shared-tool candidates, not permission to add Portable Ops hashes or
addresses to `psp-recomp`. Any upstream patch should use synthetic fixtures
and preserve the existing Killzone and Metal Gear Acid generation gates.

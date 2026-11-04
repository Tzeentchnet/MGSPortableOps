#!/usr/bin/env python3
"""Run the pinned code generator with evidence-backed title corrections."""

from pathlib import Path
import sys


def main(argv):
    if len(argv) < 4 or argv[1] != "--toolkit":
        print(
            "usage: codegen.py --toolkit <psp-recomp> <codegen arguments...>",
            file=sys.stderr,
        )
        return 2

    tools = Path(argv[2]).resolve() / "tools"
    if not (tools / "codegen.py").is_file():
        print(f"ERROR: psp-recomp tools were not found under {tools}", file=sys.stderr)
        return 1
    sys.path.insert(0, str(tools))

    import analyze

    upstream_analyze = analyze.analyze

    def title_analyze(elf):
        functions, ranges = upstream_analyze(elf)
        excluded = {
            0x088749AD,
            0x08901FE4,
            0x08901FFC,
            0x08902000,
            0x0896E664,
        }
        missing = excluded - functions
        if missing:
            found = ", ".join(f"0x{address:08x}" for address in sorted(missing))
            raise ValueError(
                f"expected false function candidates were not discovered: {found}"
            )
        unexpected_unaligned = {
            address for address in functions - excluded if address & 3
        }
        if unexpected_unaligned:
            found = ", ".join(
                f"0x{address:08x}"
                for address in sorted(unexpected_unaligned)
            )
            raise ValueError(
                f"unexpected unaligned function candidates: {found}"
            )
        print(
            "title correction: rejected one NID collision and four "
            "internal or delay-slot labels"
        )
        return functions - excluded, ranges

    analyze.analyze = title_analyze

    import codegen

    return codegen.main([str(tools / "codegen.py"), *argv[3:]])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

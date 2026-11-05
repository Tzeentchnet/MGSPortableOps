#!/usr/bin/env python3
"""Report exact RGB differences between two private PPM frame captures."""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

from ppm import read_ppm, validate_region


def compare_images(reference, candidate, region=None):
    if (
        reference.width != candidate.width
        or reference.height != candidate.height
    ):
        raise ValueError("frame dimensions do not match")
    if region is None:
        region = [0, 0, reference.width, reference.height]
    x, y, width, height = validate_region(
        region, reference.width, reference.height
    )
    changed = 0
    absolute_sum = 0
    maximum = 0
    signed_deltas = Counter()
    left = x + width
    top = y + height
    right = bottom = -1
    for row in range(y, y + height):
        for column in range(x, x + width):
            offset = (row * reference.width + column) * 3
            deltas = [
                candidate.pixels[offset + channel]
                - reference.pixels[offset + channel]
                for channel in range(3)
            ]
            absolute_deltas = [abs(delta) for delta in deltas]
            pixel_maximum = max(absolute_deltas)
            absolute_sum += sum(absolute_deltas)
            maximum = max(maximum, pixel_maximum)
            if pixel_maximum:
                signed_deltas.update(delta for delta in deltas if delta)
                changed += 1
                left = min(left, column)
                top = min(top, row)
                right = max(right, column)
                bottom = max(bottom, row)
    pixels = width * height
    return {
        "dimensions": [reference.width, reference.height],
        "region": [x, y, width, height],
        "compared_pixels": pixels,
        "different_pixels": changed,
        "different_fraction": changed / pixels,
        "max_channel_difference": maximum,
        "mean_absolute_channel_difference": absolute_sum / (pixels * 3),
        "changed_channel_delta_histogram": [
            {"delta": delta, "channels": signed_deltas[delta]}
            for delta in sorted(signed_deltas)
        ],
        "different_bounds_inclusive": (
            [left, top, right, bottom] if changed else None
        ),
        "reference_sha256": reference.sha256,
        "candidate_sha256": candidate.sha256,
        "exact_match": changed == 0,
    }


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--region", type=int, nargs=4, metavar=("X", "Y", "W", "H"))
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    report = compare_images(
        read_ppm(args.reference), read_ppm(args.candidate), args.region
    )
    report["reference"] = str(args.reference.resolve())
    report["candidate"] = str(args.candidate.resolve())
    text = json.dumps(report, indent=2, allow_nan=False) + "\n"
    if args.out:
        with args.out.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
    else:
        print(text, end="")
    return 0 if report["exact_match"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (OSError, ValueError) as error:
        print(f"frame comparison failed: {error}", file=sys.stderr)
        raise SystemExit(2)

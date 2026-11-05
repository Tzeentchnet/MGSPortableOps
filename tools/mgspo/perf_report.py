#!/usr/bin/env python3
"""Summarize bounded psp-recomp display samples without equating flips to FPS."""

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import statistics
import sys

SCHEMA = "# psp-recomp display performance v4"
COLUMNS = (
    "flip", "present", "frame_ms", "frontend_ms", "backend_ms", "gpu_ms",
    "over_budget", "gpu_source_flip", "scheduler_ms", "native_ms",
    "interpreter_ms", "hle_ms", "ge_ms", "vertex_ms", "sync_ms",
    "primitive_ms", "bezier_ms", "spline_ms", "patch_eval_ms",
    "patch_draw_ms", "vertex_decode_ms", "hle_calls", "interp_instructions",
    "ge_lists", "ge_commands", "ge_draws", "ge_vertices", "ge_through_draws",
    "ge_through_vertices", "ge_transform_draws", "ge_transform_vertices",
    "ge_transform_unique_vertices", "backend_begin_ms", "backend_vertices_ms",
    "backend_framebuffer_ms", "backend_textures_ms", "backend_draws_ms",
    "backend_present_ms", "backend_submit_ms", "backend_vertices",
    "backend_batches", "framebuffer_readbacks", "framebuffer_aliases",
    "feedback_snapshots", "feedback_snapshot_pixels", "feedback_reuses",
    "capture_ms", "texture_capture_ms", "state_capture_ms", "texture_misses",
    "texture_decode_wait_us", "pso_fallbacks", "alt_off",
)
FLOAT_COLUMNS = frozenset(name for name in COLUMNS if name.endswith("_ms"))
OPTIONAL_TIMINGS = frozenset(
    (
        "gpu_ms",
        "backend_begin_ms",
        "backend_vertices_ms",
        "backend_framebuffer_ms",
        "backend_textures_ms",
        "backend_draws_ms",
        "backend_present_ms",
        "backend_submit_ms",
    )
)
BACKEND_TIMINGS = OPTIONAL_TIMINGS - {"gpu_ms"}
CPU_CATEGORIES = (
    "scheduler_ms", "native_ms", "interpreter_ms", "hle_ms", "ge_ms",
    "vertex_ms", "sync_ms",
)
WORK_COUNTERS = (
    "hle_calls", "interp_instructions", "ge_lists", "ge_commands", "ge_draws",
    "ge_vertices", "ge_through_draws", "ge_through_vertices",
    "ge_transform_draws", "ge_transform_vertices", "ge_transform_unique_vertices",
    "framebuffer_readbacks", "framebuffer_aliases", "feedback_snapshots",
    "feedback_snapshot_pixels", "feedback_reuses", "texture_misses",
    "texture_decode_wait_us", "pso_fallbacks",
)
READBACK_HOTSPOT_LIMIT = 5


def read_capture(path):
    data = path.read_bytes()
    with io.StringIO(data.decode("utf-8"), newline="") as stream:
        if stream.readline().rstrip("\r\n") != SCHEMA:
            raise ValueError(f"{path}: unsupported performance schema")
        reader = csv.DictReader(stream, strict=True)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise ValueError(f"{path}: unexpected performance columns")

        samples = []
        gpu_sources = set()
        for row in reader:
            line = reader.line_num + 1
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"{path}:{line}: wrong number of columns")
            sample = {}
            for name in COLUMNS:
                try:
                    value = (
                        float(row[name]) if name in FLOAT_COLUMNS
                        else int(row[name], 10)
                    )
                except ValueError as error:
                    raise ValueError(
                        f"{path}:{line}: invalid {name}"
                    ) from error
                if isinstance(value, float) and not math.isfinite(value):
                    raise ValueError(f"{path}:{line}: non-finite {name}")
                if value < 0 and not (
                    name in OPTIONAL_TIMINGS and value == -1
                ):
                    raise ValueError(f"{path}:{line}: negative {name}")
                sample[name] = value
            if sample["flip"] == 0 or sample["frame_ms"] <= 0:
                raise ValueError(f"{path}:{line}: invalid flip or frame time")
            if sample["over_budget"] not in (0, 1):
                raise ValueError(f"{path}:{line}: invalid over_budget")
            unavailable = [
                sample[name] == -1 for name in BACKEND_TIMINGS
            ]
            if any(unavailable) and not all(unavailable):
                raise ValueError(
                    f"{path}:{line}: inconsistent backend timings"
                )
            source = sample["gpu_source_flip"]
            if (source == 0) != (sample["gpu_ms"] == -1):
                raise ValueError(f"{path}:{line}: inconsistent GPU sample")
            if source > sample["flip"] or (source and source in gpu_sources):
                raise ValueError(f"{path}:{line}: invalid GPU source flip")
            if source:
                gpu_sources.add(source)
            if samples and (
                sample["flip"] != samples[-1]["flip"] + 1
                or sample["present"] < samples[-1]["present"]
            ):
                raise ValueError(
                    f"{path}:{line}: discontinuous flip or decreasing present"
                )
            samples.append(sample)
    if len(samples) < 2:
        raise ValueError(f"{path}: at least two samples are required")
    return samples, hashlib.sha256(data).hexdigest()


def load_samples(path):
    return read_capture(path)[0]


def percentile(values, fraction):
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low = math.floor(position)
    high = math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def timing_summary(values):
    return {
        "mean": statistics.fmean(values),
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "max": max(values),
    }


def summarize(samples, minimum=None, maximum=None):
    if minimum is not None and minimum < 0:
        raise ValueError("minimum present must be nonnegative")
    if maximum is not None and maximum < 0:
        raise ValueError("maximum present must be nonnegative")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError("minimum present exceeds maximum present")
    selected = [
        sample for sample in samples
        if (minimum is None or sample["present"] >= minimum)
        and (maximum is None or sample["present"] <= maximum)
    ]
    if len(selected) < 2:
        raise ValueError("selected interval has fewer than two samples")

    intervals = selected[1:]
    elapsed_ms = sum(sample["frame_ms"] for sample in intervals)
    present_deltas = [
        after["present"] - before["present"]
        for before, after in zip(selected, intervals)
    ]
    source_flips = {sample["flip"] for sample in intervals}
    gpu_times = [
        sample["gpu_ms"] for sample in samples
        if sample["gpu_source_flip"] in source_flips
    ]
    backend_samples = [
        sample for sample in samples
        if sample["flip"] - 1 in source_flips
        and sample["backend_begin_ms"] >= 0
    ]
    readback_hotspots = sorted(
        (
            sample for sample in intervals
            if sample["framebuffer_readbacks"] > 0
        ),
        key=lambda sample: (-sample["framebuffer_readbacks"], sample["flip"]),
    )[:READBACK_HOTSPOT_LIMIT]
    return {
        "interval": {
            "first_flip": selected[0]["flip"],
            "last_flip": selected[-1]["flip"],
            "first_present": selected[0]["present"],
            "last_present": selected[-1]["present"],
            "flip_intervals": len(intervals),
            "elapsed_ms": elapsed_ms,
            "host_flips_per_second": 1000 * len(intervals) / elapsed_ms,
            "observed_present_transitions": sum(
                delta > 0 for delta in present_deltas
            ),
            "repeated_present_flips": sum(
                delta == 0 for delta in present_deltas
            ),
            "unobserved_present_counts": sum(
                max(0, delta - 1) for delta in present_deltas
            ),
        },
        "frame_ms": timing_summary(
            [sample["frame_ms"] for sample in intervals]
        ),
        "over_budget_flips": sum(
            sample["over_budget"] for sample in intervals
        ),
        "mean_cpu_category_ms_per_flip": {
            name: statistics.fmean(sample[name] for sample in intervals)
            for name in CPU_CATEGORIES
        },
        "mean_primitive_ms_per_flip": statistics.fmean(
            sample["primitive_ms"] for sample in intervals
        ),
        "workload_totals": {
            name: sum(sample[name] for sample in intervals)
            for name in WORK_COUNTERS
        },
        "readback_hotspots": [
            {
                "ending_flip": sample["flip"],
                "ending_present": sample["present"],
                "framebuffer_readbacks": sample["framebuffer_readbacks"],
                "frame_ms": sample["frame_ms"],
                "sync_ms": sample["sync_ms"],
                "previous_backend_present_ms": (
                    sample["backend_present_ms"]
                    if sample["backend_present_ms"] >= 0 else None
                ),
            }
            for sample in readback_hotspots
        ],
        "gpu": {
            "aligned_samples": len(gpu_times),
            "timing_ms": timing_summary(gpu_times) if gpu_times else None,
        },
        "previous_flip_backend": {
            "aligned_samples": len(backend_samples),
            "missing_samples": len(intervals) - len(backend_samples),
            "observed_vertices": (
                sum(sample["backend_vertices"] for sample in backend_samples)
                if backend_samples else None
            ),
            "observed_batches": (
                sum(sample["backend_batches"] for sample in backend_samples)
                if backend_samples else None
            ),
            "vertices": (
                sum(sample["backend_vertices"] for sample in backend_samples)
                if len(backend_samples) == len(intervals)
                else None
            ),
            "batches": (
                sum(sample["backend_batches"] for sample in backend_samples)
                if len(backend_samples) == len(intervals)
                else None
            ),
        },
        "alternate_mode_flips": sum(
            sample["alt_off"] != 0 for sample in intervals
        ),
    }


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("samples", type=Path)
    parser.add_argument("--min-present", type=int)
    parser.add_argument("--max-present", type=int)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    samples, source_sha256 = read_capture(args.samples)
    report = summarize(samples, args.min_present, args.max_present)
    report["source_sha256"] = source_sha256
    report["source"] = str(args.samples.resolve())
    report["note"] = (
        "Host flips and framebuffer-call counters are not verified guest FPS. "
        "Compare matching workloads and separately validate audio and visuals. "
        "The capture's over-budget threshold is not recorded in the CSV; "
        "some unavailable framebuffer counters are encoded as zero."
    )
    text = json.dumps(report, indent=2, allow_nan=False) + "\n"
    if args.out:
        with args.out.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (OSError, ValueError, csv.Error) as error:
        print(f"performance report failed: {error}", file=sys.stderr)
        raise SystemExit(1)

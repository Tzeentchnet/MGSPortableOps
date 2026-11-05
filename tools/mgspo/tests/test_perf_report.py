import csv
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from perf_report import (
    COLUMNS,
    FLOAT_COLUMNS,
    OPTIONAL_TIMINGS,
    SCHEMA,
    load_samples,
    main,
    summarize,
)


def sample(flip, present, frame_ms, **overrides):
    result = {
        name: -1.0 if name in OPTIONAL_TIMINGS
        else 0.0 if name in FLOAT_COLUMNS
        else 0
        for name in COLUMNS
    }
    result.update(flip=flip, present=present, frame_ms=frame_ms)
    result.update(overrides)
    return result


def write_samples(path, samples):
    with path.open("w", encoding="utf-8", newline="") as stream:
        stream.write(SCHEMA + "\n")
        writer = csv.DictWriter(stream, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(samples)


class PerformanceReportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "samples.csv"
        self.samples = [
            sample(101, 20, 9.0),
            sample(102, 20, 10.0, ge_draws=4, vertex_ms=3.0),
            sample(103, 23, 20.0, ge_draws=5, vertex_ms=7.0),
            sample(104, 24, 30.0, ge_draws=6, vertex_ms=5.0),
            sample(105, 25, 40.0, gpu_source_flip=102, gpu_ms=2.0),
            sample(106, 26, 50.0, gpu_source_flip=103, gpu_ms=3.0),
        ]
        write_samples(self.path, self.samples)

    def test_interval_distinguishes_flips_and_present_transitions(self):
        report = summarize(load_samples(self.path), 20, 24)
        interval = report["interval"]
        self.assertEqual(interval["flip_intervals"], 3)
        self.assertEqual(interval["elapsed_ms"], 60.0)
        self.assertEqual(interval["host_flips_per_second"], 50.0)
        self.assertEqual(interval["observed_present_transitions"], 2)
        self.assertEqual(interval["repeated_present_flips"], 1)
        self.assertEqual(interval["unobserved_present_counts"], 2)
        self.assertAlmostEqual(report["frame_ms"]["p95"], 29.0)
        self.assertEqual(report["workload_totals"]["ge_draws"], 15)
        self.assertEqual(
            report["mean_cpu_category_ms_per_flip"]["vertex_ms"], 5.0
        )

    def test_delayed_gpu_samples_are_aligned_by_source_flip(self):
        report = summarize(load_samples(self.path), 20, 24)
        self.assertEqual(report["gpu"]["aligned_samples"], 2)
        self.assertEqual(report["gpu"]["timing_ms"]["mean"], 2.5)

    def test_missing_gpu_samples_are_explicit(self):
        report = summarize(load_samples(self.path), 25, 26)
        self.assertEqual(report["gpu"]["aligned_samples"], 0)
        self.assertIsNone(report["gpu"]["timing_ms"])

    def test_missing_backend_timings_do_not_imply_zero_draws(self):
        report = summarize(load_samples(self.path), 20, 24)
        backend = report["previous_flip_backend"]
        self.assertEqual(backend["aligned_samples"], 0)
        self.assertEqual(backend["missing_samples"], 3)
        self.assertIsNone(backend["observed_vertices"])
        self.assertIsNone(backend["observed_batches"])
        self.assertIsNone(backend["vertices"])
        self.assertIsNone(backend["batches"])
        self.assertEqual(report["readback_hotspots"], [])

    def test_readback_hotspots_are_ranked_bounded_and_windowed(self):
        counts = (999, 888, 4, 10, 10, 0, 1, 3, 2, 500)
        samples = [
            sample(
                100 + index, 10 + index, 10.0,
                framebuffer_readbacks=count, sync_ms=float(index),
            )
            for index, count in enumerate(counts)
        ]
        samples[3].update(
            {name: 0.1 for name in OPTIONAL_TIMINGS if name != "gpu_ms"}
        )
        samples[3]["backend_present_ms"] = 2.5
        write_samples(self.path, samples)

        report = summarize(load_samples(self.path), 11, 18)
        hotspots = report["readback_hotspots"]
        self.assertEqual(
            [entry["ending_flip"] for entry in hotspots],
            [103, 104, 102, 107, 108],
        )
        self.assertEqual(
            hotspots[0],
            {
                "ending_flip": 103,
                "ending_present": 13,
                "framebuffer_readbacks": 10,
                "frame_ms": 10.0,
                "sync_ms": 3.0,
                "previous_backend_present_ms": 2.5,
            },
        )
        self.assertIsNone(hotspots[1]["previous_backend_present_ms"])

    def test_backend_counts_align_to_the_previous_flip(self):
        for row in self.samples[2:5]:
            row.update({name: 0.1 for name in OPTIONAL_TIMINGS if name != "gpu_ms"})
            row["backend_vertices"] = 4
            row["backend_batches"] = 2
        write_samples(self.path, self.samples)
        report = summarize(load_samples(self.path), 20, 24)
        backend = report["previous_flip_backend"]
        self.assertEqual(backend["aligned_samples"], 3)
        self.assertEqual(backend["missing_samples"], 0)
        self.assertEqual(backend["observed_vertices"], 12)
        self.assertEqual(backend["observed_batches"], 6)
        self.assertEqual(backend["vertices"], 12)
        self.assertEqual(backend["batches"], 6)

    def test_rejects_bad_schema_and_columns(self):
        self.path.write_text("invalid\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "schema"):
            load_samples(self.path)
        self.path.write_text(SCHEMA + "\nflip,present\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "columns"):
            load_samples(self.path)

    def test_rejects_discontinuity_and_nonfinite_timings(self):
        self.samples[2]["flip"] = 104
        write_samples(self.path, self.samples)
        with self.assertRaisesRegex(ValueError, "discontinuous"):
            load_samples(self.path)
        self.samples[2]["flip"] = 103
        self.samples[2]["frame_ms"] = float("nan")
        write_samples(self.path, self.samples)
        with self.assertRaisesRegex(ValueError, "non-finite"):
            load_samples(self.path)

    def test_rejects_malformed_gpu_timing(self):
        self.samples[3]["gpu_ms"] = 3.0
        write_samples(self.path, self.samples)
        with self.assertRaisesRegex(ValueError, "inconsistent GPU"):
            load_samples(self.path)

    def test_rejects_duplicate_gpu_source(self):
        self.samples[5]["gpu_source_flip"] = 102
        write_samples(self.path, self.samples)
        with self.assertRaisesRegex(ValueError, "GPU source"):
            load_samples(self.path)

    def test_rejects_empty_or_inverted_interval(self):
        samples = load_samples(self.path)
        with self.assertRaisesRegex(ValueError, "fewer than two"):
            summarize(samples, 100, 200)
        with self.assertRaisesRegex(ValueError, "exceeds"):
            summarize(samples, 24, 20)

    def test_report_output_is_exclusive(self):
        output = Path(self.directory.name) / "report.json"
        self.assertEqual(
            main([str(self.path), "--max-present", "24", "--out", str(output)]),
            0,
        )
        self.assertTrue(output.is_file())
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(
            report["source_sha256"], hashlib.sha256(self.path.read_bytes()).hexdigest()
        )
        with self.assertRaises(FileExistsError):
            main([str(self.path), "--out", str(output)])


if __name__ == "__main__":
    unittest.main()

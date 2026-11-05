import json
from pathlib import Path
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from frame_diff import compare_images, main
from ppm import read_ppm


class FrameDiffTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.reference = Path(self.directory.name) / "reference.ppm"
        self.candidate = Path(self.directory.name) / "candidate.ppm"
        self.reference.write_bytes(
            b"P6\n# comment\n2 2\n255\n"
            b"\x00\x01\x02\x03\x04\x05"
            b"\x06\x07\x08\x09\x0a\x0b"
        )
        self.candidate.write_bytes(
            b"P6\r\n2 2\r\n255\r\n"
            b"\x00\x01\x02\x03\x04\x05"
            b"\x06\x08\x08\x09\x0a\x0d"
        )

    def test_exact_rgb_metrics_and_bounds(self):
        report = compare_images(read_ppm(self.reference), read_ppm(self.candidate))
        self.assertEqual(report["dimensions"], [2, 2])
        self.assertEqual(report["compared_pixels"], 4)
        self.assertEqual(report["different_pixels"], 2)
        self.assertEqual(report["different_fraction"], 0.5)
        self.assertEqual(report["max_channel_difference"], 2)
        self.assertEqual(report["mean_absolute_channel_difference"], 0.25)
        self.assertEqual(
            report["changed_channel_delta_histogram"],
            [{"delta": 1, "channels": 1}, {"delta": 2, "channels": 1}],
        )
        self.assertEqual(report["different_bounds_inclusive"], [0, 1, 1, 1])
        self.assertFalse(report["exact_match"])

    def test_histogram_counts_signed_changed_channels(self):
        self.candidate.write_bytes(
            b"P6\n2 2\n255\n"
            b"\x00\x00\x02\x04\x03\x05"
            b"\x06\x08\x08\x09\x0a\x0d"
        )
        report = compare_images(read_ppm(self.reference), read_ppm(self.candidate))
        self.assertEqual(
            report["changed_channel_delta_histogram"],
            [
                {"delta": -1, "channels": 2},
                {"delta": 1, "channels": 2},
                {"delta": 2, "channels": 1},
            ],
        )

    def test_region_can_match_despite_other_differences(self):
        report = compare_images(
            read_ppm(self.reference), read_ppm(self.candidate), [0, 0, 2, 1]
        )
        self.assertTrue(report["exact_match"])
        self.assertEqual(report["different_pixels"], 0)
        self.assertEqual(report["changed_channel_delta_histogram"], [])
        self.assertIsNone(report["different_bounds_inclusive"])

    def test_rejects_bad_dimensions_and_region(self):
        self.candidate.write_bytes(b"P6\n1 1\n255\n\x00\x01\x02")
        with self.assertRaisesRegex(ValueError, "dimensions do not match"):
            compare_images(read_ppm(self.reference), read_ppm(self.candidate))
        with self.assertRaisesRegex(ValueError, "outside"):
            compare_images(
                read_ppm(self.reference), read_ppm(self.reference), [1, 1, 2, 1]
            )

    def test_rejects_truncated_pixels_and_missing_separator(self):
        self.candidate.write_bytes(b"P6\n1 1\n255\n\x00")
        with self.assertRaisesRegex(ValueError, "truncated"):
            read_ppm(self.candidate)
        self.candidate.write_bytes(b"P6\n1 1\n255#\x00\x01\x02")
        with self.assertRaisesRegex(ValueError, "separator"):
            read_ppm(self.candidate)

    def test_mismatch_writes_report_and_returns_failure(self):
        output = Path(self.directory.name) / "report.json"
        self.assertEqual(
            main([str(self.reference), str(self.candidate), "--out", str(output)]),
            1,
        )
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertFalse(report["exact_match"])
        self.assertEqual(report["different_pixels"], 2)
        with self.assertRaises(FileExistsError):
            main([str(self.reference), str(self.candidate), "--out", str(output)])


if __name__ == "__main__":
    unittest.main()

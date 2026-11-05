import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace


TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import oracle


def valid_config():
    return {
        "oracle": {
            "ppsspp": {
                "repository": "https://github.com/hrydgard/ppsspp.git",
                "version": "1.20.4",
                "commit": "f" * 40,
                "patch": "tools/mgspo/ppsspp/boot_oracle.patch",
                "trace_format": 1,
                "trace_steps": 100000,
                "build": {
                    **oracle.EXPECTED_BUILD,
                    "cmake_options": ["HEADLESS=ON"],
                },
                "settings": dict(oracle.EXPECTED_SETTINGS),
            },
        },
        "disc": {
            "id": "ULUS10202",
            "version": "1.00",
            "iso_size": 1024,
            "iso_sha1": "a" * 40,
            "files": {"BOOT.BIN": "b" * 40},
        },
        "module": {
            "file": "BOOT.BIN",
            "name": "mgp_main",
            "base": 0x08804000,
            "entry": 0x08804128,
            "gp": 0x08A07E90,
            "text_size": 0x100,
            "image_size": 0x200,
            "start_thread": {"verified": False},
        },
    }


class OracleConfigTests(unittest.TestCase):
    def test_accepts_pinned_unverified_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parsed = oracle.validate_config(
                valid_config(),
                root / "config.toml",
                root,
            )
            self.assertEqual(parsed.trace_steps, 100000)
            self.assertEqual(parsed.version, "1.20.4")

    def test_rejects_short_commit(self):
        config = valid_config()
        config["oracle"]["ppsspp"]["commit"] = "fa50bb1"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(
                oracle.OracleError,
                "40 lowercase",
            ):
                oracle.validate_config(
                    config,
                    root / "config.toml",
                    root,
                )

    def test_rejects_unverified_measured_values(self):
        config = valid_config()
        config["module"]["start_thread"]["uid"] = 0x119
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(
                oracle.OracleError,
                "unverified.*measured",
            ):
                oracle.validate_config(
                    config,
                    root / "config.toml",
                    root,
                )

    def test_verified_contract_requires_every_field(self):
        config = valid_config()
        config["module"]["start_thread"] = {"verified": True}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(
                oracle.OracleError,
                "is missing",
            ):
                oracle.validate_config(
                    config,
                    root / "config.toml",
                    root,
                )

    def test_accepts_complete_verified_contract(self):
        config = valid_config()
        values = {
            "verified": True,
            "module_uid": 0x112,
            "uid": 0x113,
            "priority": 0x20,
            "stack_start": 0x09FFFC00,
            "stack_size": 0x400,
            "attr": 0x80000000,
            "effective_attr": 0x800000FF,
            "next_uid": 0x114,
            "initial_ge_list_id": 0x0,
            "initial_hcount": 10,
            "argument_hex": (
                "64697363303a2f5053505f47414d452f5359534449522f"
                "45424f4f542e42494e00"
            ),
            "argument_address": 0x09FFFED0,
            "initial_sp": 0x09FFFE90,
            "initial_k0": 0x09FFFF00,
            "initial_ra": 0x08000030,
            "initial_gpr_fill": 0xDEADBEEF,
            "initial_hi": 0xDEADBEEF,
            "initial_lo": 0xDEADBEEF,
            "initial_fcr31": 0xE00,
            "initial_fpcond": 0,
            "initial_fpr_fill_bits": 0x7F800001,
            "initial_vfpu_fill_bits": 0,
            "prepared_stack_sha256": (
                "d0e481fc998fd1c30806c46271b8cd9174896535fa03610a5"
                "a928e4ad0e2935c"
            ),
            "initial_vfpu_control": [
                0xE4,
                0xE4,
                0,
                0x3F,
                0,
                0,
                0,
                0x7772CEAB,
                0x3F800001,
                0x3F800002,
                0x3F800004,
                0x3F800008,
                0x3F800000,
                0x3F800000,
                0x3F800000,
                0x3F800000,
            ],
        }
        config["module"]["start_thread"] = values
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parsed = oracle.validate_config(
                config,
                root / "config.toml",
                root,
            )
            self.assertTrue(parsed.module["start_thread"]["verified"])

    def test_rejects_setting_drift(self):
        config = valid_config()
        config["oracle"]["ppsspp"]["settings"][
            "cpu_core"
        ] = "jit"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(
                oracle.OracleError,
                "cpu_core",
            ):
                oracle.validate_config(
                    config,
                    root / "config.toml",
                    root,
                )


class OracleBuildIdentityTests(unittest.TestCase):
    def test_extracts_msvc_banner_from_mixed_streams(self):
        output = (
            "usage: cl [ option... ] filename... [ /link linkoption... ]\n"
            "Microsoft (R) C/C++ Optimizing Compiler Version "
            "19.44.35229 for x64\n"
        )
        with mock.patch.object(
            oracle,
            "_command_output",
            return_value=output,
        ):
            version = oracle._msvc_version("cl.exe", {})
        self.assertEqual(
            version,
            "Microsoft (R) C/C++ Optimizing Compiler Version "
            "19.44.35229 for x64",
        )

    def build_fixture(self, root):
        patch = root / "oracle.patch"
        executable = root / "PPSSPPHeadless.exe"
        identity_path = root / "mgspo_oracle_build.json"
        patch.write_bytes(b"pinned patch")
        executable.write_bytes(b"pinned executable")
        config = SimpleNamespace(
            version="1.20.4",
            commit="f" * 40,
            patch=patch,
            build={
                "target": "PPSSPPHeadless",
                "configuration": "Release",
                "architecture": "x64",
            },
        )
        identity = {
            "schema": 1,
            "ppsspp_version": config.version,
            "ppsspp_commit": config.commit,
            "patch_sha256": oracle.hash_file(patch),
            "configuration": "Release",
            "architecture": "x64",
            "executable_sha256": oracle.hash_file(executable),
            "compiler": "MSVC",
            "vc_tools_version": "14",
            "visual_studio": "17",
            "windows_sdk": "10",
            "cmake": "cmake",
            "ninja": "ninja",
        }
        identity_path.write_text(json.dumps(identity), encoding="utf-8")
        return config, identity_path, executable, identity

    def test_accepts_matching_build_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            config, path, executable, identity = self.build_fixture(Path(directory))
            self.assertEqual(
                oracle.verify_build_identity(config, path, executable),
                identity,
            )

    def test_rejects_stale_patch_and_executable(self):
        for changed in ("patch", "executable"):
            with self.subTest(changed=changed):
                with tempfile.TemporaryDirectory() as directory:
                    config, path, executable, _ = self.build_fixture(Path(directory))
                    target = config.patch if changed == "patch" else executable
                    target.write_bytes(b"changed")
                    with self.assertRaisesRegex(
                        oracle.OracleError, f"{changed}_sha256 mismatch"
                    ):
                        oracle.verify_build_identity(config, path, executable)

    def test_rejects_missing_compiler_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            config, path, executable, identity = self.build_fixture(Path(directory))
            identity["compiler"] = ""
            path.write_text(json.dumps(identity), encoding="utf-8")
            with self.assertRaisesRegex(oracle.OracleError, "compiler"):
                oracle.verify_build_identity(config, path, executable)

    def test_capture_rejects_stale_build_before_creating_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config, path, executable, _ = self.build_fixture(root)
            executable.write_bytes(b"changed")
            output = root / "capture"
            with mock.patch.object(oracle, "verify_checkout"), mock.patch.object(
                oracle, "verify_iso"
            ) as verify_iso:
                with self.assertRaisesRegex(oracle.OracleError, "executable_sha256"):
                    oracle.capture_oracle(
                        config, root, root, root / "disc.iso", output
                    )
            verify_iso.assert_not_called()
            self.assertFalse(output.exists())


class OracleCompareTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def write_capture(self, name, trace_lines):
        capture = self.root / name
        capture.mkdir()
        identity = {
            "disc_id": "ULUS10202",
            "ppsspp": {"commit": "f" * 40},
            "trace_steps": len(trace_lines),
        }
        (capture / "boot_state.json").write_text(
            json.dumps({"entry_pc": 0x08804128}, sort_keys=True),
            encoding="utf-8",
        )
        (capture / "events.jsonl").write_text(
            '{"event":"start"}\n',
            encoding="utf-8",
        )
        (capture / "stack.bin").write_bytes(b"\xff" * 32)
        (capture / "cpu.trace").write_text(
            "# psp-recomp trace v1 oracle=ppsspp\n"
            + "\n".join(trace_lines)
            + "\n",
            encoding="ascii",
        )
        (capture / "trace.done").write_text(
            f"{len(trace_lines)}\n", encoding="ascii"
        )
        manifest = {
            "schema": 1,
            "identity": identity,
            "files": {
                name: {
                    "size": (capture / name).stat().st_size,
                    "sha256": oracle.hash_file(capture / name),
                }
                for name in oracle.CAPTURE_FILES
            },
        }
        self.write_manifest(capture, manifest)
        return capture

    def write_manifest(self, capture, manifest):
        path = capture / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        (capture / "capture.complete").write_text(
            oracle.hash_file(path) + "\n", encoding="ascii"
        )

    def test_identical_captures_match(self):
        lines = [
            "0 pc=0x08804128 op=0x27bdfff0 r29=0x09ffff00",
            "1 pc=0x0880412c op=0x03e00008",
        ]
        first = self.write_capture("first", lines)
        second = self.write_capture("second", lines)
        oracle.compare_captures(first, second)

    def test_reports_register_divergence_with_context(self):
        first = self.write_capture(
            "first",
            [
                "0 pc=0x08804128 op=0x24020001 r2=0x00000001",
                "1 pc=0x0880412c op=0x03e00008",
            ],
        )
        second = self.write_capture(
            "second",
            [
                "0 pc=0x08804128 op=0x24020001 r2=0x00000002",
                "1 pc=0x0880412c op=0x03e00008",
            ],
        )
        with self.assertRaisesRegex(
            oracle.OracleError,
            "divergence at step 0",
        ):
            oracle.compare_captures(first, second)

    def test_rejects_identity_drift(self):
        lines = ["0 pc=0x08804128 op=0x00000000"]
        first = self.write_capture("first", lines)
        second = self.write_capture("second", lines)
        manifest_path = second / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["identity"]["disc_id"] = "different"
        self.write_manifest(second, manifest)
        with self.assertRaisesRegex(
            oracle.OracleError,
            "identity manifests differ",
        ):
            oracle.compare_captures(first, second)

    def test_rejects_missing_capture_completion(self):
        capture = self.write_capture(
            "incomplete", ["0 pc=0x08804128 op=0x00000000"]
        )
        (capture / "capture.complete").unlink()
        with self.assertRaisesRegex(oracle.OracleError, "completion marker"):
            oracle.verify_capture(capture)

    def test_rejects_tampered_capture_payload(self):
        capture = self.write_capture(
            "tampered", ["0 pc=0x08804128 op=0x00000000"]
        )
        (capture / "stack.bin").write_bytes(b"changed")
        with self.assertRaisesRegex(oracle.OracleError, "stack.bin.*manifest"):
            oracle.verify_capture(capture)

    def test_rejects_truncated_matching_traces(self):
        lines = ["0 pc=0x08804128 op=0x00000000"]
        first = self.write_capture("first-truncated", lines)
        second = self.write_capture("second-truncated", lines)
        for capture in (first, second):
            manifest = json.loads(
                (capture / "manifest.json").read_text(encoding="utf-8")
            )
            manifest["identity"]["trace_steps"] = 2
            (capture / "trace.done").write_text("2\n", encoding="ascii")
            manifest["files"]["trace.done"] = {
                "size": (capture / "trace.done").stat().st_size,
                "sha256": oracle.hash_file(capture / "trace.done"),
            }
            self.write_manifest(capture, manifest)
        with self.assertRaisesRegex(oracle.OracleError, "contain 1 and 1 steps"):
            oracle.compare_captures(first, second)

    def test_identical_standalone_trace_matches(self):
        lines = [
            "0 pc=0x08804128 op=0x24020001 r2=0x00000001",
            "1 pc=0x0880412c op=0x03e00008",
        ]
        reference = self.write_capture("reference", lines) / "cpu.trace"
        candidate = self.write_capture("candidate", lines) / "cpu.trace"
        Path(str(candidate) + ".done").write_text("2\n", encoding="ascii")
        oracle.compare_cpu_traces(reference, candidate, 2)

    def test_standalone_trace_accepts_guest_import_jump(self):
        reference_lines = [
            "0 pc=0x089c9a28 op=0x0a2dd8b6",
            "1 pc=0x089c9a2c op=0x00000000",
            "2 pc=0x08b762d8 op=0x27bdfff0 r29=0x09fbf930",
        ]
        candidate_lines = [
            "0 pc=0x089c9a28 op=0x03e00008",
            "1 pc=0x089c9a2c op=0x00000000",
            "2 pc=0x08b762d8 op=0x27bdfff0 r29=0x09fbf930",
        ]
        reference = (
            self.write_capture("reference-jump", reference_lines)
            / "cpu.trace"
        )
        candidate = (
            self.write_capture("candidate-jump", candidate_lines)
            / "cpu.trace"
        )
        Path(str(candidate) + ".done").write_text("3\n", encoding="ascii")
        oracle.compare_cpu_traces(reference, candidate, 3)

    def test_standalone_trace_requires_completion_marker(self):
        lines = ["0 pc=0x08804128 op=0x00000000"]
        reference = self.write_capture("reference", lines) / "cpu.trace"
        candidate = self.write_capture("candidate", lines) / "cpu.trace"
        with self.assertRaisesRegex(
            oracle.OracleError,
            "completion marker does not exist",
        ):
            oracle.compare_cpu_traces(reference, candidate, 1)


if __name__ == "__main__":
    unittest.main()

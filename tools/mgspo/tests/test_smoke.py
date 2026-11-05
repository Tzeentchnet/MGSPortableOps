import copy
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from smoke import (
    MISSION_BASE,
    MISSION_MODULE,
    MISSION_ACTIVE_MARKER,
    D3D12_COHERENCY_MARKER,
    D3D12_HARDWARE_TEXTURE_MARKER,
    D3D12_PRESENT_BATCH_MARKER,
    PAUSE_MARKER,
    DEFAULT_CONFIG,
    expected_plaintext_module_lifecycle,
    expected_plaintext_module_stops,
    parse_args,
    read_interpreter_profile,
    read_mission_activation,
    read_pause_checkpoint,
    sha256_file,
    sha256_ppm_region,
    validate_log,
    validate_module_lifecycle,
    validate_plaintext_module_lifecycle,
    validate_plaintext_module_stops,
)


class SmokeTests(unittest.TestCase):
    def test_native_zlib_is_default(self):
        args = parse_args(
            ["smoke.py", "runtime.exe", "game.iso", "--out", "result"]
        )
        self.assertTrue(args.native_zlib)
        self.assertEqual(args.renderer, "sw")

    def test_d3d12_is_explicit(self):
        args = parse_args(
            [
                "smoke.py",
                "runtime.exe",
                "game.iso",
                "--out",
                "result",
                "--renderer",
                "d3d12",
            ]
        )
        self.assertEqual(args.renderer, "d3d12")

    def test_interpreted_zlib_is_explicit(self):
        args = parse_args(
            [
                "smoke.py",
                "runtime.exe",
                "game.iso",
                "--out",
                "result",
                "--interpreted-zlib",
            ]
        )
        self.assertFalse(args.native_zlib)

    def test_sha256_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "frame.ppm"
            path.write_bytes(b"frame")
            self.assertEqual(
                sha256_file(path),
                "9dff50df08c635815f4b19da10f756605a34a79a48d4ba48712782502975a70e",
            )

    def test_sha256_ppm_region(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "frame.ppm"
            path.write_bytes(
                b"P6\n2 2\n255\n"
                b"\x01\x02\x03\x04\x05\x06"
                b"\x07\x08\x09\x0a\x0b\x0c"
            )
            self.assertEqual(
                sha256_ppm_region(path, [1, 0, 1, 2]),
                "fe8248e55e25320a8d0612fc52886dbd"
                "e7d7d372f08a437e9bf2c825379aa2f6",
            )

    def test_sha256_ppm_region_rejects_out_of_bounds_region(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "frame.ppm"
            path.write_bytes(b"P6\n1 1\n255\n\x00\x00\x00")
            with self.assertRaisesRegex(ValueError, "outside"):
                sha256_ppm_region(path, [1, 0, 1, 1])

    def test_validate_log_accepts_mission_checkpoint(self):
        validate_log(
            "gui_init: GE backend sw\n"
            f"module loader: allocated {MISSION_MODULE} at "
            f"{MISSION_BASE}-08c5a300\n"
            "module loader: HLE-only module libfont.prx uid=0x128\n"
            "module loader: ZLIB uid=0x11b base=08b20000 "
            "size=4100 entry=08b216b4 gp=08b2c090\n"
            f"{MISSION_ACTIVE_MARKER}6900 vblank=4100\n"
            f"{PAUSE_MARKER}7050 vblank=4200\n",
            7000,
        )

    def test_validate_log_accepts_opt_in_native_zlib(self):
        validate_log(
            "gui_init: GE backend d3d12\n"
            f"{D3D12_COHERENCY_MARKER}\n"
            f"{D3D12_HARDWARE_TEXTURE_MARKER} (title default)\n"
            f"{D3D12_PRESENT_BATCH_MARKER} targets=2\n"
            f"module loader: allocated {MISSION_MODULE} at "
            f"{MISSION_BASE}-08c5a300\n"
            "module loader: HLE-only module libfont.prx uid=0x128\n"
            "module loader: ZLIB uid=0x11b base=08b20000 "
            "size=4100 entry=08b216b4 gp=08b2c090 (native)\n"
            f"{MISSION_ACTIVE_MARKER}6900 vblank=4100\n"
            f"{PAUSE_MARKER}7050 vblank=4200\n",
            7000,
            native_zlib=True,
            renderer="d3d12",
        )

    def test_validate_log_requires_d3d12_hardware_texture_path(self):
        with self.assertRaisesRegex(ValueError, "hardware texture path enabled"):
            validate_log(
                "gui_init: GE backend d3d12\n"
                f"{D3D12_COHERENCY_MARKER}\n"
                f"{D3D12_PRESENT_BATCH_MARKER} targets=2\n"
                f"module loader: allocated {MISSION_MODULE} at "
                f"{MISSION_BASE}-08c5a300\n"
                "module loader: HLE-only module libfont.prx uid=0x128\n"
                "module loader: ZLIB uid=0x11b base=08b20000 "
                "size=4100 entry=08b216b4 gp=08b2c090 (native)\n"
                f"{MISSION_ACTIVE_MARKER}6900 vblank=4100\n"
                f"{PAUSE_MARKER}7050 vblank=4200\n",
                7000,
                native_zlib=True,
                renderer="d3d12",
            )

    def test_validate_log_rejects_wrong_renderer(self):
        with self.assertRaisesRegex(ValueError, "GE backend d3d12"):
            validate_log(
                "gui_init: GE backend sw\n"
                f"module loader: allocated {MISSION_MODULE} at "
                f"{MISSION_BASE}-08c5a300\n"
                "module loader: HLE-only module libfont.prx uid=0x128\n"
                "module loader: ZLIB uid=0x11b base=08b20000 "
                "size=4100 entry=08b216b4 gp=08b2c090 (native)\n"
                f"{MISSION_ACTIVE_MARKER}6900 vblank=4100\n"
                f"{PAUSE_MARKER}7050 vblank=4200\n",
                7000,
                native_zlib=True,
                renderer="d3d12",
            )

    def test_validate_log_rejects_gpu_coherency_warning(self):
        with self.assertRaisesRegex(ValueError, "newer GPU framebuffer"):
            validate_log(
                "gui_init: GE backend d3d12\n"
                f"{D3D12_COHERENCY_MARKER}\n"
                f"{D3D12_PRESENT_BATCH_MARKER} targets=2\n"
                "ged3d12: CPU write invalidated a newer GPU framebuffer\n"
                f"module loader: allocated {MISSION_MODULE} at "
                f"{MISSION_BASE}-08c5a300\n"
                "module loader: HLE-only module libfont.prx uid=0x128\n"
                "module loader: ZLIB uid=0x11b base=08b20000 "
                "size=4100 entry=08b216b4 gp=08b2c090 (native)\n"
                f"{MISSION_ACTIVE_MARKER}6900 vblank=4100\n"
                f"{PAUSE_MARKER}7050 vblank=4200\n",
                7000,
                native_zlib=True,
                renderer="d3d12",
            )

    def test_validate_log_requires_d3d12_write_synchronization(self):
        with self.assertRaisesRegex(ValueError, "write synchronization enabled"):
            validate_log(
                "gui_init: GE backend d3d12\n"
                f"module loader: allocated {MISSION_MODULE} at "
                f"{MISSION_BASE}-08c5a300\n"
                "module loader: HLE-only module libfont.prx uid=0x128\n"
                "module loader: ZLIB uid=0x11b base=08b20000 "
                "size=4100 entry=08b216b4 gp=08b2c090 (native)\n"
                f"{MISSION_ACTIVE_MARKER}6900 vblank=4100\n"
                f"{PAUSE_MARKER}7050 vblank=4200\n",
                7000,
                native_zlib=True,
                renderer="d3d12",
            )

    def test_validate_log_requires_safe_present_batching(self):
        with self.assertRaisesRegex(ValueError, "batched CPU-present readback"):
            validate_log(
                "gui_init: GE backend d3d12\n"
                f"{D3D12_COHERENCY_MARKER}\n"
                f"module loader: allocated {MISSION_MODULE} at "
                f"{MISSION_BASE}-08c5a300\n"
                "module loader: HLE-only module libfont.prx uid=0x128\n"
                "module loader: ZLIB uid=0x11b base=08b20000 "
                "size=4100 entry=08b216b4 gp=08b2c090 (native)\n"
                f"{MISSION_ACTIVE_MARKER}6900 vblank=4100\n"
                f"{PAUSE_MARKER}7050 vblank=4200\n",
                7000,
                native_zlib=True,
                renderer="d3d12",
            )

    def test_validate_log_rejects_unsafe_present_batching(self):
        with self.assertRaisesRegex(ValueError, "batching skipped"):
            validate_log(
                "gui_init: GE backend d3d12\n"
                f"{D3D12_COHERENCY_MARKER}\n"
                f"{D3D12_PRESENT_BATCH_MARKER} targets=2\n"
                "mgspo: D3D12 CPU-present batching skipped for "
                "current-generation GPU work\n"
                f"module loader: allocated {MISSION_MODULE} at "
                f"{MISSION_BASE}-08c5a300\n"
                "module loader: HLE-only module libfont.prx uid=0x128\n"
                "module loader: ZLIB uid=0x11b base=08b20000 "
                "size=4100 entry=08b216b4 gp=08b2c090 (native)\n"
                f"{MISSION_ACTIVE_MARKER}6900 vblank=4100\n"
                f"{PAUSE_MARKER}7050 vblank=4200\n",
                7000,
                native_zlib=True,
                renderer="d3d12",
            )

    def test_validate_log_rejects_unrequested_native_zlib(self):
        with self.assertRaisesRegex(ValueError, "interpreted"):
            validate_log(
                "gui_init: GE backend sw\n"
                f"module loader: allocated {MISSION_MODULE} at "
                f"{MISSION_BASE}-08c5a300\n"
                "module loader: HLE-only module libfont.prx uid=0x128\n"
                "module loader: ZLIB uid=0x11b base=08b20000 "
                "size=4100 entry=08b216b4 gp=08b2c090 (native)\n"
                f"{MISSION_ACTIVE_MARKER}6900 vblank=4100\n"
                f"{PAUSE_MARKER}7050 vblank=4200\n",
                7000,
            )

    def test_validate_log_rejects_trapping_fallback(self):
        with self.assertRaisesRegex(ValueError, "failure markers"):
            validate_log(
                "gui_init: GE backend sw\n"
                f"module loader: allocated {MISSION_MODULE} at "
                f"{MISSION_BASE}-08c5a300\n"
                "module loader: HLE-only module libfont.prx uid=0x128\n"
                "module loader: ZLIB uid=0x11b base=08b20000 "
                "size=4100 entry=08b216b4 gp=08b2c090\n"
                "dispatch: interpreter stopped at 0x08b248f0\n"
                f"{MISSION_ACTIVE_MARKER}6900 vblank=4100\n"
                f"{PAUSE_MARKER}7050 vblank=4200\n",
                7000,
            )

    def test_read_mission_activation(self):
        self.assertEqual(
            read_mission_activation(
                f"{MISSION_ACTIVE_MARKER}6800 vblank=4000\n"
            ),
            {"present": 6800, "vblank": 4000},
        )

    def test_read_pause_checkpoint(self):
        self.assertEqual(
            read_pause_checkpoint(
                f"other output\n{PAUSE_MARKER}7068 vblank=4211\n"
            ),
            {"present": 7068, "vblank": 4211},
        )

    def test_read_pause_checkpoint_rejects_duplicate_markers(self):
        with self.assertRaisesRegex(ValueError, "expected one"):
            read_pause_checkpoint(
                f"{PAUSE_MARKER}7068 vblank=4211\n"
                f"{PAUSE_MARKER}7069 vblank=4212\n"
            )

    def test_validate_module_lifecycle_accepts_ordered_reuse(self):
        def module_event(sequence, action, uid, path, base, size):
            return {
                "sequence": sequence,
                "category": "module",
                "event": action,
                "uid": uid,
                "path": path,
                "base": f"0x{base:08x}",
                "size": size,
            }

        events = [
            module_event(0, "loaded", "0x1", "stage-a", 0x08AFB800, 0x500),
            module_event(1, "loaded", "0x2", "stage-b", 0x08B86F00, 0x1000),
            module_event(2, "unloaded", "0x1", "stage-a", 0x08AFB800, 0x500),
            module_event(3, "loaded", "0x3", "stage-c", 0x08AFB800, 0x600),
            module_event(4, "unloaded", "0x2", "stage-b", 0x08B86F00, 0x1000),
            module_event(
                5,
                "loaded",
                "0x4",
                MISSION_MODULE,
                0x08B86F00,
                0xD3400,
            ),
        ]
        result = validate_module_lifecycle(events)
        self.assertEqual(result["unload_count"], 2)
        self.assertEqual(
            result["reused_bases"],
            ["0x08afb800", "0x08b86f00"],
        )

    def test_validate_module_lifecycle_rejects_active_overlap(self):
        events = [
            {
                "sequence": 0,
                "category": "module",
                "event": "loaded",
                "uid": "0x1",
                "path": "stage-a",
                "base": "0x08afb800",
                "size": 0x600,
            },
            {
                "sequence": 1,
                "category": "module",
                "event": "loaded",
                "uid": "0x2",
                "path": "stage-b",
                "base": "0x08afba00",
                "size": 0x600,
            },
        ]
        with self.assertRaisesRegex(ValueError, "overlaps active"):
            validate_module_lifecycle(events)

    def test_validate_plaintext_module_lifecycle_accepts_contract(self):
        with DEFAULT_CONFIG.open("rb") as stream:
            modules = tomllib.load(stream)["plaintext_modules"]
        events = expected_plaintext_module_lifecycle(modules)
        for sequence, event in enumerate(events):
            event["sequence"] = sequence
        result = validate_plaintext_module_lifecycle(events, modules)
        self.assertEqual(
            result["callback_threads"],
            ["0x11c", "0x121"],
        )
        self.assertEqual(
            result["worker_threads"],
            ["0x122", "0x125"],
        )

    def test_validate_plaintext_module_lifecycle_rejects_wrong_gp(self):
        with DEFAULT_CONFIG.open("rb") as stream:
            modules = tomllib.load(stream)["plaintext_modules"]
        events = copy.deepcopy(
            expected_plaintext_module_lifecycle(modules)
        )
        kjfs_started = next(
            event
            for event in events
            if event.get("category") == "thread"
            and event.get("event") == "started"
            and event.get("name") == "KCEJ_FS"
        )
        kjfs_started["gp"] = "0xdeadbeef"
        with self.assertRaisesRegex(ValueError, "gp"):
            validate_plaintext_module_lifecycle(events, modules)

    def test_validate_plaintext_module_stops_accepts_contract(self):
        with DEFAULT_CONFIG.open("rb") as stream:
            modules = tomllib.load(stream)["plaintext_modules"]
        events = expected_plaintext_module_stops(modules)
        for sequence, event in enumerate(events):
            event["sequence"] = sequence
        result = validate_plaintext_module_stops(events, modules)
        self.assertEqual(
            result["stop_order"],
            ["KCEJ_FS", "KCEJ_SOUND2", "ZLIB"],
        )
        self.assertEqual(
            result["callback_threads"],
            ["0x127", "0x128"],
        )

    def test_validate_plaintext_module_stops_rejects_exit_status(self):
        with DEFAULT_CONFIG.open("rb") as stream:
            modules = tomllib.load(stream)["plaintext_modules"]
        events = copy.deepcopy(
            expected_plaintext_module_stops(modules)
        )
        zlib_deleted = next(
            event
            for event in events
            if event.get("category") == "thread"
            and event.get("event") == "deleted"
            and event.get("name") == "ZLIB"
        )
        zlib_deleted["exit_status"] = "0x00000001"
        with self.assertRaisesRegex(ValueError, "exit_status"):
            validate_plaintext_module_stops(events, modules)

    def test_read_interpreter_profile_ranks_modules(self):
        content = (
            "# psp-recomp interpreter profile v1\n"
            "module\ttarget\tcalls\tinstructions\tsyscalls\t"
            "native_handoffs\tstep_limits\treturns\tfailures\n"
            "ZLIB\t0x08b216b4\t2\t100\t1\t0\t0\t1\t0\n"
            "KCEJ_FS\t0x08b77ae8\t3\t250\t2\t1\t0\t2\t0\n"
            "ZLIB\t0x08b21718\t4\t200\t0\t0\t0\t4\t0\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.tsv"
            path.write_text(content, encoding="utf-8")
            profile = read_interpreter_profile(path)
        self.assertEqual(profile["total_calls"], 9)
        self.assertEqual(profile["total_instructions"], 550)
        self.assertEqual(
            [item["module"] for item in profile["modules"]],
            ["ZLIB", "KCEJ_FS"],
        )
        self.assertEqual(profile["modules"][0]["instructions"], 300)
        self.assertEqual(profile["top_targets"][0]["target"], "0x08b77ae8")


if __name__ == "__main__":
    unittest.main()

import argparse
import json
from pathlib import Path
import sys
import tempfile
import unittest


TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import manager


class ManagerStateTests(unittest.TestCase):
    def test_state_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manager.json"
            state = manager.ManagerState(
                iso_path=str(Path(directory) / "game.iso"),
                install_path=str(Path(directory) / "install"),
                build="software",
            )
            manager.save_state(state, path)
            self.assertEqual(manager.load_state(path), state)
            self.assertTrue(path.read_text(encoding="utf-8").endswith("\n"))

    def test_state_rejects_unknown_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manager.json"
            path.write_text(
                json.dumps(
                    {
                        "iso_path": "",
                        "install_path": str(Path(directory) / "install"),
                        "build": "d3d12",
                        "secret": "unexpected",
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                manager.ManagerError, "unknown fields"
            ):
                manager.load_state(path)

    def test_build_argument_updates_default_install_path(self):
        state = manager.ManagerState()
        arguments = argparse.Namespace(
            iso=None,
            install_dir=None,
            build="software",
        )
        updated = manager.state_from_args(arguments, state)
        self.assertEqual(updated.build, "software")
        self.assertEqual(
            Path(updated.install_path),
            manager.BUILD_CONFIGS["software"]["default_install"],
        )


class GraphicsSettingsTests(unittest.TestCase):
    def test_graphics_round_trip(self):
        expected = manager.GraphicsSettings(
            renderer="d3d12",
            internal_resolution=4,
            texture_scale=3,
            d3d12_full_rate=True,
            anti_aliasing="smaa",
            skip_startup=True,
        )
        self.assertEqual(
            manager.parse_graphics_text(expected.to_text()), expected
        )

    def test_graphics_save_is_runtime_compatible(self):
        with tempfile.TemporaryDirectory() as directory:
            install = Path(directory)
            settings = manager.GraphicsSettings(renderer="sw")
            path = manager.save_graphics_settings(
                install, settings, build="software"
            )
            self.assertEqual(path.name, "graphics.ini")
            self.assertEqual(
                manager.load_graphics_settings(install), settings
            )
            self.assertNotIn(".tmp", path.read_text(encoding="utf-8"))

    def test_software_build_rejects_d3d12(self):
        with self.assertRaisesRegex(
            manager.ManagerError, "does not contain"
        ):
            manager.GraphicsSettings().validate("software")

    def test_software_renderer_rejects_smaa(self):
        with self.assertRaisesRegex(manager.ManagerError, "SMAA"):
            manager.GraphicsSettings(
                renderer="sw", anti_aliasing="smaa"
            ).validate()


class WorkflowTests(unittest.TestCase):
    def test_workflow_uses_selected_preset_and_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            iso = root / "game.iso"
            iso.write_bytes(b"test")
            install = root / "install"
            state = manager.ManagerState(
                iso_path=str(iso),
                install_path=str(install),
                build="d3d12",
            )
            commands = manager.workflow_commands(state)
            self.assertEqual(
                commands[0],
                ["git", "submodule", "update", "--init", "--recursive"],
            )
            self.assertEqual(
                commands[3],
                [
                    "cmake",
                    "--preset",
                    "clang-cl-d3d12-experimental",
                ],
            )
            self.assertEqual(
                commands[4],
                ["cmake", "--build", "--preset", "mgspo-d3d12-experimental"],
            )
            self.assertEqual(commands[5][-2:], ["--prefix", str(install)])

    def test_iso_size_mismatch_fails_before_hashing(self):
        with tempfile.TemporaryDirectory() as directory:
            iso = Path(directory) / "wrong.iso"
            iso.write_bytes(b"not the supported image")
            with self.assertRaisesRegex(manager.ManagerError, "ISO size"):
                manager.verify_iso(iso, log=lambda _line: None)


if __name__ == "__main__":
    unittest.main()

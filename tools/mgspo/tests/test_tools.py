import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from extract import disc_destination, module_kind
from gen import apply_title_replacements
from iso9660 import Iso, sha1_file


class ToolTests(unittest.TestCase):
    def test_module_kind(self):
        self.assertEqual(module_kind(b"\x7fELFdata"), "elf")
        self.assertEqual(module_kind(b"~PSPdata"), "encrypted")
        self.assertEqual(module_kind(b"~SCEdata"), "encrypted")
        self.assertEqual(module_kind(b"other"), "data")

    def test_disc_destination_rejects_parent_components(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(
                disc_destination(root, "/PSP_GAME/USRDIR/data.bin"),
                root / "PSP_GAME" / "USRDIR" / "data.bin",
            )
            with self.assertRaisesRegex(ValueError, "unsafe ISO path"):
                disc_destination(root, "/PSP_GAME/../outside.bin")

    def test_sha1_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.bin"
            path.write_bytes(b"portable ops")
            self.assertEqual(
                sha1_file(path),
                hashlib.sha1(b"portable ops").hexdigest(),
            )

    def test_invalid_iso_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.iso"
            path.write_bytes(b"\0" * (17 * 2048))
            with self.assertRaisesRegex(ValueError, "no ISO9660"):
                Iso(path)

    def test_applies_measured_memcpy_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mgspo_recomp_000.c"
            path.write_text(
                "void f_089cf880(CpuState *s) {\n"
                "    original(s);\n"
                "}\n\n"
                "void f_089cf900(CpuState *s) {\n"
                "    keep(s);\n"
                "}\n",
                encoding="utf-8",
            )
            apply_title_replacements([path])
            content = path.read_text(encoding="utf-8")
            self.assertIn("0x6a00000du", content)
            self.assertIn("MEM_W8(destination + offset", content)
            self.assertNotIn("original(s)", content)
            self.assertIn("keep(s)", content)


if __name__ == "__main__":
    unittest.main()

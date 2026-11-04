import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from extract import module_kind
from iso9660 import Iso, sha1_file


class ToolTests(unittest.TestCase):
    def test_module_kind(self):
        self.assertEqual(module_kind(b"\x7fELFdata"), "elf")
        self.assertEqual(module_kind(b"~PSPdata"), "encrypted")
        self.assertEqual(module_kind(b"~SCEdata"), "encrypted")
        self.assertEqual(module_kind(b"other"), "data")

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


if __name__ == "__main__":
    unittest.main()

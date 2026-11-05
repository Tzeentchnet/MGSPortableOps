import sys
import unittest

sys.path.insert(0, str(__file__).rsplit("\\", 2)[0])

from module_lifecycle import parse_args


class ModuleLifecycleTests(unittest.TestCase):
    def test_native_zlib_is_default(self):
        args = parse_args(
            [
                "module_lifecycle.py",
                "runtime.exe",
                "game.iso",
                "--out",
                "result",
            ]
        )
        self.assertFalse(args.interpreted_zlib)

    def test_interpreted_zlib_is_explicit(self):
        args = parse_args(
            [
                "module_lifecycle.py",
                "runtime.exe",
                "game.iso",
                "--out",
                "result",
                "--interpreted-zlib",
            ]
        )
        self.assertTrue(args.interpreted_zlib)


if __name__ == "__main__":
    unittest.main()

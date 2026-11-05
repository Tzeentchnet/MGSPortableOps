import hashlib
from pathlib import Path
import sys
import unittest


TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import boot_contract
from test_oracle import valid_config


class BootContractTests(unittest.TestCase):
    def test_reconstructs_measured_prepared_stack(self):
        config = valid_config()
        start = config["module"]["start_thread"]
        start.update(
            {
                "verified": True,
                "module_uid": 0x112,
                "uid": 0x113,
                "priority": 0x20,
                "stack_start": 0x09FFFC00,
                "stack_size": 0x400,
                "attr": 0x80000000,
                "effective_attr": 0x800000FF,
                "next_uid": 0x114,
                "initial_ge_list_id": 0,
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
                "initial_vfpu_control": [0] * 16,
                "prepared_stack_sha256": (
                    "d0e481fc998fd1c30806c46271b8cd9174896535fa03610a5"
                    "a928e4ad0e2935c"
                ),
            }
        )
        stack = boot_contract.build_prepared_stack(start)
        self.assertEqual(len(stack), 0x400)
        self.assertEqual(
            hashlib.sha256(stack).hexdigest(),
            start["prepared_stack_sha256"],
        )
        self.assertEqual(stack[0:4], b"\x13\x01\x00\x00")
        self.assertEqual(
            stack[0x2D0:0x2F1],
            bytes.fromhex(start["argument_hex"]),
        )


if __name__ == "__main__":
    unittest.main()

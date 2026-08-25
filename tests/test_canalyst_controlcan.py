import ctypes
import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "windows"
    / "canalyst_controlcan.py"
)
SPEC = importlib.util.spec_from_file_location("canalyst_controlcan", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
sys.modules["canalyst_controlcan"] = MODULE

OUTPUT_MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "windows"
    / "canalyst_output_command.py"
)
OUTPUT_SPEC = importlib.util.spec_from_file_location(
    "canalyst_output_command", OUTPUT_MODULE_PATH
)
assert OUTPUT_SPEC is not None and OUTPUT_SPEC.loader is not None
OUTPUT_MODULE = importlib.util.module_from_spec(OUTPUT_SPEC)
OUTPUT_SPEC.loader.exec_module(OUTPUT_MODULE)


class ControlCanLayoutTests(unittest.TestCase):
    def test_vendor_structure_sizes(self) -> None:
        self.assertEqual(ctypes.sizeof(MODULE.VciInitConfig), 16)
        self.assertEqual(ctypes.sizeof(MODULE.VciCanObject), 24)

    def test_frame_record_uses_only_dlc_bytes(self) -> None:
        frame = MODULE.VciCanObject()
        frame.ID = 0x18FF50E5
        frame.TimeStamp = 1234
        frame.TimeFlag = 1
        frame.ExternFlag = 1
        frame.DataLen = 3
        frame.Data[:] = (0x10, 0x20, 0x30, 0xAA, 0xAA, 0xAA, 0xAA, 0xAA)

        record = MODULE.frame_to_record(frame, 7)

        self.assertEqual(record["sequence"], 7)
        self.assertEqual(record["identifier_hex"], "0x18FF50E5")
        self.assertEqual(record["frame_format"], "extended")
        self.assertEqual(record["dlc"], 3)
        self.assertEqual(record["data_hex"], "10 20 30")

    def test_output_on_wire_frame(self) -> None:
        frame = OUTPUT_MODULE.build_output_frame(True)

        self.assertEqual(frame.ID, 0x01250000)
        self.assertEqual(frame.ExternFlag, 1)
        self.assertEqual(frame.DataLen, 8)
        self.assertEqual(
            bytes(frame.Data),
            bytes((0x01, 0, 0, 0, 0x01, 0, 0, 0)),
        )

    def test_output_off_wire_frame(self) -> None:
        frame = OUTPUT_MODULE.build_output_frame(False)

        self.assertEqual(frame.ID, 0x01250000)
        self.assertEqual(
            bytes(frame.Data),
            bytes((0x01, 0, 0, 0, 0x00, 0, 0, 0)),
        )


if __name__ == "__main__":
    unittest.main()

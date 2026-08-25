#!/usr/bin/env python3
"""Headless CAN1 monitor for CANalyst-II through vendor ControlCAN.dll."""

from __future__ import annotations

import argparse
import csv
import ctypes
import json
import os
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STATUS_OK = 1
STATUS_ERROR = 0
VCI_USBCAN2 = 4
DEVICE_INDEX = 0
CAN1_API_INDEX = 0
RECEIVE_ERROR = 0xFFFFFFFF

BIT_TIMINGS: dict[int, tuple[int, int]] = {
    1_000_000: (0x00, 0x14),
    800_000: (0x00, 0x16),
    500_000: (0x00, 0x1C),
    250_000: (0x01, 0x1C),
    125_000: (0x03, 0x1C),
}


class VciInitConfig(ctypes.Structure):
    _fields_ = [
        ("AccCode", ctypes.c_uint32),
        ("AccMask", ctypes.c_uint32),
        ("Reserved", ctypes.c_uint32),
        ("Filter", ctypes.c_uint8),
        ("Timing0", ctypes.c_uint8),
        ("Timing1", ctypes.c_uint8),
        ("Mode", ctypes.c_uint8),
    ]


class VciCanObject(ctypes.Structure):
    _fields_ = [
        ("ID", ctypes.c_uint32),
        ("TimeStamp", ctypes.c_uint32),
        ("TimeFlag", ctypes.c_uint8),
        ("SendType", ctypes.c_uint8),
        ("RemoteFlag", ctypes.c_uint8),
        ("ExternFlag", ctypes.c_uint8),
        ("DataLen", ctypes.c_uint8),
        ("Data", ctypes.c_uint8 * 8),
        ("Reserved", ctypes.c_uint8 * 3),
    ]


def configure_api(dll: Any) -> None:
    uint32 = ctypes.c_uint32
    int32 = ctypes.c_int32

    dll.VCI_OpenDevice.argtypes = [uint32, uint32, uint32]
    dll.VCI_OpenDevice.restype = uint32
    dll.VCI_CloseDevice.argtypes = [uint32, uint32]
    dll.VCI_CloseDevice.restype = uint32
    dll.VCI_InitCAN.argtypes = [uint32, uint32, uint32, ctypes.POINTER(VciInitConfig)]
    dll.VCI_InitCAN.restype = uint32
    dll.VCI_StartCAN.argtypes = [uint32, uint32, uint32]
    dll.VCI_StartCAN.restype = uint32
    dll.VCI_ResetCAN.argtypes = [uint32, uint32, uint32]
    dll.VCI_ResetCAN.restype = uint32
    dll.VCI_GetReceiveNum.argtypes = [uint32, uint32, uint32]
    dll.VCI_GetReceiveNum.restype = uint32
    dll.VCI_Receive.argtypes = [
        uint32,
        uint32,
        uint32,
        ctypes.POINTER(VciCanObject),
        uint32,
        int32,
    ]
    dll.VCI_Receive.restype = uint32


def frame_to_record(frame: VciCanObject, sequence: int) -> dict[str, Any]:
    data_length = min(int(frame.DataLen), 8)
    payload = bytes(frame.Data[:data_length])
    return {
        "sequence": sequence,
        "host_time_utc": datetime.now(timezone.utc).isoformat(),
        "device_timestamp_raw": int(frame.TimeStamp),
        "time_flag": int(frame.TimeFlag),
        "identifier": int(frame.ID),
        "identifier_hex": f"0x{int(frame.ID):08X}",
        "frame_format": "extended" if frame.ExternFlag else "standard",
        "frame_type": "remote" if frame.RemoteFlag else "data",
        "dlc": data_length,
        "data_hex": payload.hex(" ").upper(),
    }


def write_result(path: Path, result: dict[str, Any]) -> None:
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dll", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--firmware-commit", required=True)
    parser.add_argument("--bridge-commit", required=True)
    parser.add_argument("--seconds", type=int, default=15)
    parser.add_argument("--bitrate", type=int, default=1_000_000, choices=BIT_TIMINGS)
    parser.add_argument("--channel", type=int, default=1, choices=(1,))
    parser.add_argument("--print-limit", type=int, default=50)
    parser.add_argument("--require-frames", action="store_true")
    return parser.parse_args()


def run(args: argparse.Namespace) -> int:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    result_path = args.output_dir / "result.json"
    frames_path = args.output_dir / "frames.csv"
    started_at = datetime.now(timezone.utc)
    result: dict[str, Any] = {
        "status": "error",
        "host": platform.node(),
        "platform": platform.platform(),
        "python_bits": ctypes.sizeof(ctypes.c_void_p) * 8,
        "firmware_commit": args.firmware_commit,
        "firmware_commit_source": "dispatcher_label",
        "firmware_commit_verified_on_target": False,
        "bridge_commit": args.bridge_commit,
        "device_type": VCI_USBCAN2,
        "device_index": DEVICE_INDEX,
        "physical_channel": "CAN1",
        "api_channel_index": CAN1_API_INDEX,
        "bitrate": args.bitrate,
        "mode": "normal",
        "duration_seconds": args.seconds,
        "started_at_utc": started_at.isoformat(),
        "frame_count": 0,
    }

    device_open = False
    can_started = False
    dll: Any | None = None

    try:
        if os.name != "nt":
            raise RuntimeError("ControlCAN.dll monitor requires Windows")
        if args.seconds <= 0:
            raise ValueError("--seconds must be positive")
        if not args.dll.is_file():
            raise FileNotFoundError(f"ControlCAN.dll not found: {args.dll}")
        if ctypes.sizeof(VciInitConfig) != 16:
            raise RuntimeError(f"unexpected VCI_INIT_CONFIG size: {ctypes.sizeof(VciInitConfig)}")
        if ctypes.sizeof(VciCanObject) != 24:
            raise RuntimeError(f"unexpected VCI_CAN_OBJ size: {ctypes.sizeof(VciCanObject)}")

        dll = ctypes.WinDLL(str(args.dll))
        configure_api(dll)

        if dll.VCI_OpenDevice(VCI_USBCAN2, DEVICE_INDEX, 0) != STATUS_OK:
            raise RuntimeError("VCI_OpenDevice failed")
        device_open = True

        timing0, timing1 = BIT_TIMINGS[args.bitrate]
        init = VciInitConfig(
            AccCode=0,
            AccMask=0xFFFFFFFF,
            Reserved=0,
            Filter=1,
            Timing0=timing0,
            Timing1=timing1,
            Mode=0,
        )
        if dll.VCI_InitCAN(VCI_USBCAN2, DEVICE_INDEX, CAN1_API_INDEX, ctypes.byref(init)) != STATUS_OK:
            raise RuntimeError("VCI_InitCAN failed")
        if dll.VCI_StartCAN(VCI_USBCAN2, DEVICE_INDEX, CAN1_API_INDEX) != STATUS_OK:
            raise RuntimeError("VCI_StartCAN failed")
        can_started = True

        fieldnames = [
            "sequence",
            "host_time_utc",
            "device_timestamp_raw",
            "time_flag",
            "identifier",
            "identifier_hex",
            "frame_format",
            "frame_type",
            "dlc",
            "data_hex",
        ]
        sequence = 0
        deadline = time.monotonic() + args.seconds
        with frames_path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
            writer.writeheader()

            while time.monotonic() < deadline:
                pending = int(dll.VCI_GetReceiveNum(VCI_USBCAN2, DEVICE_INDEX, CAN1_API_INDEX))
                if pending == RECEIVE_ERROR:
                    raise RuntimeError("VCI_GetReceiveNum failed")
                if pending == 0:
                    time.sleep(0.005)
                    continue

                batch_size = min(pending, 512)
                batch = (VciCanObject * batch_size)()
                received = int(
                    dll.VCI_Receive(
                        VCI_USBCAN2,
                        DEVICE_INDEX,
                        CAN1_API_INDEX,
                        batch,
                        batch_size,
                        100,
                    )
                )
                if received == RECEIVE_ERROR:
                    raise RuntimeError("VCI_Receive failed")

                for index in range(received):
                    sequence += 1
                    record = frame_to_record(batch[index], sequence)
                    writer.writerow(record)
                    if sequence <= args.print_limit:
                        print(
                            f"RX#{sequence} {record['frame_format']} "
                            f"id={record['identifier_hex']} dlc={record['dlc']} "
                            f"data={record['data_hex']}"
                        )

        result["frame_count"] = sequence
        result["status"] = "passed" if sequence > 0 or not args.require_frames else "failed"
        result["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        if args.require_frames and sequence == 0:
            result["error"] = "No physical CAN1 frames received"
            write_result(result_path, result)
            print("RESULT frames=0 status=failed")
            return 4

        write_result(result_path, result)
        print(f"RESULT frames={sequence} status={result['status']}")
        return 0
    except Exception as error:
        result["error"] = str(error)
        result["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        write_result(result_path, result)
        print(f"ERROR {error}", file=sys.stderr)
        return 3
    finally:
        if dll is not None and can_started:
            dll.VCI_ResetCAN(VCI_USBCAN2, DEVICE_INDEX, CAN1_API_INDEX)
        if dll is not None and device_open:
            dll.VCI_CloseDevice(VCI_USBCAN2, DEVICE_INDEX)


def main() -> int:
    return run(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())

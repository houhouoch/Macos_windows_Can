#!/usr/bin/env python3
"""Send one UDP3900 power-output command and capture physical CAN replies."""

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

from canalyst_controlcan import (
    BIT_TIMINGS,
    CAN1_API_INDEX,
    DEVICE_INDEX,
    RECEIVE_ERROR,
    STATUS_OK,
    VCI_USBCAN2,
    VciCanObject,
    VciInitConfig,
    configure_api,
    frame_to_record,
)


OUTPUT_REQUEST_IDENTIFIER = 0x01150000
OUTPUT_ACK_IDENTIFIER_ADDRESS_1 = 0x11150001
OUTPUT_ACTION = 1
OUTPUT_ACK_ACCEPTED = 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dll", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--target", required=True, choices=("on", "off"))
    parser.add_argument("--listen-seconds", type=int, default=3)
    parser.add_argument("--bitrate", type=int, default=1_000_000, choices=BIT_TIMINGS)
    return parser.parse_args()


def build_output_frame(target_on: bool) -> VciCanObject:
    frame = VciCanObject()
    frame.ID = OUTPUT_REQUEST_IDENTIFIER
    frame.TimeStamp = 0
    frame.TimeFlag = 0
    frame.SendType = 0
    frame.RemoteFlag = 0
    frame.ExternFlag = 1
    frame.DataLen = 8
    payload = (1, 0, 0, 0, 1 if target_on else 0, 0, 0, 0)
    frame.Data[:] = payload
    frame.Reserved[:] = (0, 0, 0)
    return frame


def acknowledgement_from_record(record: dict[str, Any]) -> dict[str, Any] | None:
    if record["identifier"] != OUTPUT_ACK_IDENTIFIER_ADDRESS_1:
        return None
    payload = bytes.fromhex(record["data_hex"])
    if len(payload) != 8:
        return None
    action = int.from_bytes(payload[0:2], "little")
    result = int.from_bytes(payload[2:4], "little")
    if action != OUTPUT_ACTION:
        return None
    return {
        "responder_address": 1,
        "action": action,
        "result": result,
        "accepted": result == OUTPUT_ACK_ACCEPTED,
        "frame": record,
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    result_path = args.output_dir / "result.json"
    frames_path = args.output_dir / "frames.csv"
    target_on = args.target == "on"
    request = build_output_frame(target_on)
    request_payload = bytes(request.Data[: request.DataLen])
    result: dict[str, Any] = {
        "status": "error",
        "host": platform.node(),
        "target": args.target,
        "physical_channel": "CAN1",
        "api_channel_index": CAN1_API_INDEX,
        "bitrate": args.bitrate,
        "mode": "normal",
        "request_identifier": f"0x{OUTPUT_REQUEST_IDENTIFIER:08X}",
        "request_payload": request_payload.hex(" ").upper(),
        "listen_seconds": args.listen_seconds,
        "automatic_off_sent": False,
        "transmitted_frames": 0,
        "received_frames": 0,
        "acknowledgements": [],
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    device_open = False
    can_started = False
    dll: Any | None = None
    try:
        if os.name != "nt":
            raise RuntimeError("ControlCAN.dll output command requires Windows")
        if args.listen_seconds <= 0:
            raise ValueError("--listen-seconds must be positive")
        if not args.dll.is_file():
            raise FileNotFoundError(f"ControlCAN.dll not found: {args.dll}")

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

        transmitted = int(
            dll.VCI_Transmit(
                VCI_USBCAN2,
                DEVICE_INDEX,
                CAN1_API_INDEX,
                ctypes.byref(request),
                1,
            )
        )
        result["transmitted_frames"] = transmitted
        if transmitted != 1:
            raise RuntimeError(f"VCI_Transmit returned {transmitted}, expected 1")
        print(
            f"TX target={args.target.upper()} id=0x{OUTPUT_REQUEST_IDENTIFIER:08X} "
            f"data={request_payload.hex(' ').upper()}"
        )

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
        acknowledgements: list[dict[str, Any]] = []
        deadline = time.monotonic() + args.listen_seconds
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
                    acknowledgement = acknowledgement_from_record(record)
                    if acknowledgement is not None:
                        acknowledgements.append(acknowledgement)
                        print(
                            f"ACK address=1 result={acknowledgement['result']} "
                            f"accepted={acknowledgement['accepted']}"
                        )

        result["received_frames"] = sequence
        result["acknowledgements"] = acknowledgements
        result["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        accepted = any(item["accepted"] for item in acknowledgements)
        result["status"] = "passed" if accepted else "failed"
        if not accepted:
            result["error"] = "No accepted output acknowledgement from address 1"
        write_json(result_path, result)
        print(
            f"RESULT target={args.target} tx={transmitted} rx={sequence} "
            f"accepted_ack={int(accepted)} automatic_off_sent=0"
        )
        return 0 if accepted else 4
    except Exception as error:
        result["error"] = str(error)
        result["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        write_json(result_path, result)
        print(f"ERROR {error}", file=sys.stderr)
        return 3
    finally:
        if dll is not None and can_started:
            dll.VCI_ResetCAN(VCI_USBCAN2, DEVICE_INDEX, CAN1_API_INDEX)
        if dll is not None and device_open:
            dll.VCI_CloseDevice(VCI_USBCAN2, DEVICE_INDEX)


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))

#!/usr/bin/env python3
"""End-to-end smoke test for Mantice preview audio and live controls."""

from __future__ import annotations

import asyncio
import copy
import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import websockets

from engine.preset_loader import load_preset
from engine.web_server import _preset_to_ui_params


ROOT = Path(__file__).resolve().parent


def available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def wait_for_server(port: int, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/api/version"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("Local Mantice server did not become ready")


async def exercise_preview(port: int) -> None:
    params = _preset_to_ui_params(
        load_preset(ROOT / "presets" / "essentials" / "Simple Drone.yaml")
    )
    request_id = "release-smoke-patch"
    audio = meters = queued = applied = False

    async with websockets.connect(
        f"ws://127.0.0.1:{port}/ws/preview",
        max_size=None,
    ) as websocket:
        await websocket.send(json.dumps({
            "action": "start",
            "params": params,
            "seed": 42,
        }))
        for _ in range(60):
            message = await asyncio.wait_for(websocket.recv(), timeout=10)
            if isinstance(message, bytes):
                audio = len(message) > 0
            else:
                data = json.loads(message)
                status = data.get("status")
                if status == "meters":
                    diagnostics = data.get("diagnostics") or {}
                    meters = (
                        isinstance(data.get("layers"), list)
                        and diagnostics.get("chunks_sent", 0) >= 3
                    )
                elif status == "patch_queued":
                    queued = data.get("request_id") == request_id
                elif status == "patch_applied":
                    applied = data.get("request_id") == request_id
                elif status == "reload_required":
                    raise RuntimeError(f"Smoke-test patch rejected: {data}")

            if audio and meters and not queued and not applied:
                changed = copy.deepcopy(params)
                changed["layers"][0]["muted"] = True
                await websocket.send(json.dumps({
                    "action": "patch",
                    "params": changed,
                    "request_id": request_id,
                }))
            if all((audio, meters, queued, applied)):
                await websocket.send(json.dumps({"action": "stop"}))
                return

    raise RuntimeError(
        "Incomplete preview smoke test: "
        f"audio={audio}, meters={meters}, queued={queued}, applied={applied}"
    )


def main() -> int:
    port = available_port()
    command = [
        sys.executable,
        "-c",
        (
            "from engine.web_server import launch_gui; "
            f"launch_gui(port={port}, open_browser=False)"
        ),
    ]
    server = subprocess.Popen(
        command,
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_for_server(port)
        asyncio.run(exercise_preview(port))
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)

    print("WebSocket preview smoke passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

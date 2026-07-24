import json
import unittest

import numpy as np

from engine.web_server import _active_streams, _stream_audio


class _FakeEngine:
    SR = 22050

    def __init__(self):
        self.revision = 0

    def next_chunk(self, size):
        return np.zeros((size, 2), dtype=np.float32)

    def get_peak_meters(self):
        return [-12.5, -24.0]

    def get_live_patch_state(self):
        return self.revision, None


class _FakeWebSocket:
    def __init__(self, stream_id):
        self.stream_id = stream_id
        self.binary_frames = 0
        self.messages = []

    async def send_bytes(self, _payload):
        self.binary_frames += 1

    async def send_text(self, payload):
        self.messages.append(json.loads(payload))
        _active_streams[self.stream_id] = False


class WebSocketMeteringTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_sends_session_engine_meters(self):
        stream_id = "meter-test"
        socket = _FakeWebSocket(stream_id)
        _active_streams[stream_id] = True
        try:
            await _stream_audio(socket, _FakeEngine(), stream_id)
        finally:
            _active_streams.pop(stream_id, None)

        self.assertEqual(socket.binary_frames, 3)
        self.assertEqual(len(socket.messages), 1)
        message = socket.messages[0]
        self.assertEqual(message["status"], "meters")
        self.assertEqual(message["layers"], [-12.5, -24.0])
        self.assertGreaterEqual(message["diagnostics"]["generation_ms"], 0.0)
        self.assertGreaterEqual(message["diagnostics"]["ahead_ms"], 0.0)
        self.assertEqual(message["diagnostics"]["chunks_sent"], 3)


if __name__ == "__main__":
    unittest.main()

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class LocalWebRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = (ROOT / "engine" / "web_server.py").read_text()

    def test_hosted_server_defaults_to_memory_guarded(self):
        self.assertIn("app.state.local_web_interface = False", self.server)

    def test_local_launcher_enables_unrestricted_rendering(self):
        self.assertIn("app.state.local_web_interface = True", self.server)
        self.assertIn(
            "if not app.state.local_web_interface and estimated_total_mb > MAX_MEMORY_MB:",
            self.server,
        )

    def test_local_journey_rendering_is_also_unrestricted(self):
        self.assertIn(
            "if not preview and not app.state.local_web_interface and estimated_total_mb > MAX_MEMORY_MB:",
            self.server,
        )


if __name__ == "__main__":
    unittest.main()

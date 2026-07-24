import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class WorkflowClarityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "engine" / "static" / "index.html").read_text(
            encoding="utf-8"
        )

    def test_primary_workflow_has_three_clear_stages(self):
        self.assertIn('data-workflow-tab="play"', self.html)
        self.assertIn('data-workflow-tab="shape"', self.html)
        self.assertIn('data-workflow-tab="finish"', self.html)
        self.assertIn('data-workflows="play shape"', self.html)
        self.assertIn('data-workflows="shape"', self.html)
        self.assertIn('data-workflows="finish"', self.html)

    def test_workflow_preserves_context_and_user_choice(self):
        self.assertIn('id="workflow-context"', self.html)
        self.assertIn("function updateWorkflowContext()", self.html)
        self.assertIn("localStorage.setItem('mantice-workflow'", self.html)
        self.assertIn("localStorage.getItem('mantice-workflow')", self.html)
        self.assertIn("guidePreviousWorkflow = activeWorkflow", self.html)
        self.assertIn("setWorkflow(guidePreviousWorkflow, false)", self.html)

    def test_deep_dive_reveals_the_stage_it_is_explaining(self):
        self.assertIn(
            "id === 'layers-card' || id === 'global-fx-card'",
            self.html,
        )
        self.assertIn("setWorkflow('shape', false)", self.html)
        self.assertIn("setWorkflow('finish', false)", self.html)

    def test_diagnostics_are_optional_and_measure_the_live_path(self):
        self.assertIn('id="btn-diagnostics"', self.html)
        self.assertIn('id="diagnostics-panel" hidden', self.html)
        self.assertIn("msg.status === 'patch_applied'", self.html)
        self.assertIn("liveDiagnostics.underruns++", self.html)
        self.assertIn("currentBrowserQueueMs()", self.html)
        self.assertIn("msg.diagnostics?.generation_ms", self.html)

    def test_workflow_helpers_are_extracted_and_deployment_matches(self):
        local_module = (ROOT / "engine" / "static" / "mantice-ui-core.js").read_bytes()
        deployed_module = (ROOT / "docs" / "mantice-ui-core.js").read_bytes()
        self.assertEqual(local_module, deployed_module)
        self.assertIn(b"function normalizeWorkflow", local_module)
        self.assertIn(b"function contextLabel", local_module)
        self.assertIn('<script src="mantice-ui-core.js"></script>', self.html)


if __name__ == "__main__":
    unittest.main()

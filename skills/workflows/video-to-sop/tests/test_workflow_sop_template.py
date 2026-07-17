import unittest
from pathlib import Path


TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "workflow-sop.md"
SKILL = Path(__file__).resolve().parents[1] / "SKILL.md"


class WorkflowSopTemplateTests(unittest.TestCase):
    def test_template_keeps_client_review_material_before_detail(self):
        text = TEMPLATE.read_text(encoding="utf-8")
        required = [
            "## Workflow purpose and scope",
            "## Current-state workflow outline",
            "## Verification questions for the client",
            "## Detailed extraction and source evidence",
            "## Automation-relevant observations",
            "## Source and confidence notes",
        ]
        positions = [text.index(heading) for heading in required]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("draft-for-client-verification", text)
        self.assertIn("Needs client verification", text)

    def test_template_is_client_agnostic(self):
        text = TEMPLATE.read_text(encoding="utf-8")
        self.assertNotIn("Private Client Name", text)
        self.assertIn("{Client}", text)
        self.assertIn("{Workflow}", text)

    def test_skill_routes_vision_by_evidence_need_with_explicit_approval(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("explicit approval", text)
        self.assertIn("visual evidence is material", text)
        self.assertIn("only a transcript is supplied", text)

    def test_skill_reuses_one_packet_for_multiple_workstreams(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("Multiple workstreams in one recording", text)
        self.assertIn("extract the recording once", text)
        self.assertIn("separate canonical SOPs", text)

    def test_skill_accepts_a_supplied_transcript_without_video(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("Direct supplied-transcript route", text)
        self.assertIn("without a video or URL", text)
        self.assertIn("Skip video acquisition", text)

    def test_skill_documents_reference_docx_rendering(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn('REFERENCE_DOCX="/path/to/approved-reference.docx"', text)
        self.assertIn("fails closed if that file is missing", text)

    def test_skill_separates_lightweight_youtube_and_client_workflow_lanes(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("Lane 1: Lightweight YouTube resource SOP", text)
        self.assertIn("one Markdown file in Resources", text)
        self.assertIn("Do not create a resumable workflow packet", text)
        self.assertIn("Lane 2: Client current-state workflow SOP", text)
        self.assertIn("automatically select Lane 1", text)


if __name__ == "__main__":
    unittest.main()

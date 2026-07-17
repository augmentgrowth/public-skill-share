import os
import re
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
RENDERER = SKILL_ROOT / "scripts" / "render_google_docx.sh"
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def set_normal_color(docx_path: Path, value: str) -> None:
    repacked = docx_path.with_suffix(".repacked.docx")
    with zipfile.ZipFile(docx_path) as source, zipfile.ZipFile(repacked, "w") as target:
        for item in source.infolist():
            payload = source.read(item.filename)
            if item.filename == "word/styles.xml":
                styles = payload.decode("utf-8")
                styles, replacements = re.subn(
                    r'(<w:style\b[^>]*w:styleId="Normal"[^>]*>.*?)(</w:style>)',
                    rf'\1<w:rPr><w:color w:val="{value}" /></w:rPr>\2',
                    styles,
                    count=1,
                    flags=re.DOTALL,
                )
                assert replacements == 1
                payload = styles.encode("utf-8")
            target.writestr(item, payload)
    os.replace(repacked, docx_path)


def get_normal_color(docx_path: Path) -> str:
    with zipfile.ZipFile(docx_path) as archive:
        root = ET.fromstring(archive.read("word/styles.xml"))
    color = root.find(
        f".//{{{WORD_NS}}}style[@{{{WORD_NS}}}styleId='Normal']/"
        f"{{{WORD_NS}}}rPr/{{{WORD_NS}}}color"
    )
    assert color is not None
    return color.attrib[f"{{{WORD_NS}}}val"]


class GoogleDocxExportTests(unittest.TestCase):
    def test_conservative_export_round_trips_required_sections(self):
        if shutil.which("pandoc") is None:
            self.skipTest("pandoc is not installed; local DOCX round-trip not available")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "workflow.md"
            output = root / "workflow.docx"
            source.write_text(
                "# Workflow\n\n"
                "## Current-state workflow outline\n\n1. Open the system.\n\n"
                "## Verification questions for the client\n\n- [ ] Confirm owner.\n\n"
                "## Detailed extraction and source evidence\n\nEvidence.\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [str(RENDERER), str(source), str(output)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(output.exists())
            receipt = (root / "workflow.docx.validation.json").read_text(encoding="utf-8")
            self.assertIn("validated-local-roundtrip", receipt)
            self.assertIn("section_character_counts", receipt)

    def test_reference_docx_is_applied_and_missing_reference_fails_closed(self):
        if shutil.which("pandoc") is None:
            self.skipTest("pandoc is not installed; local DOCX rendering not available")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "workflow.md"
            reference = root / "reference.docx"
            output = root / "styled.docx"
            source.write_text(
                "# Workflow\n\n"
                "## Current-state workflow outline\n\n1. Open the system.\n\n"
                "## Verification questions for the client\n\n- Confirm owner.\n\n"
                "## Detailed extraction and source evidence\n\nDetailed evidence body.\n",
                encoding="utf-8",
            )
            subprocess.run(["pandoc", str(source), "-o", str(reference)], check=True)
            set_normal_color(reference, "123456")

            env = {**os.environ, "REFERENCE_DOCX": str(reference)}
            result = subprocess.run(
                [str(RENDERER), str(source), str(output)],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(get_normal_color(output), "123456")

            env["REFERENCE_DOCX"] = str(root / "missing.docx")
            missing = subprocess.run(
                [str(RENDERER), str(source), str(root / "missing-output.docx")],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
            self.assertEqual(missing.returncode, 1)
            self.assertIn("REFERENCE_DOCX not found", missing.stderr)


if __name__ == "__main__":
    unittest.main()

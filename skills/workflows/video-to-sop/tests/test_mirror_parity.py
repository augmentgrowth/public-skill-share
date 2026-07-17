import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT / ".harness-shared" / "skills" / "video-to-skill"
MIRRORS = [
    ROOT / "03_Resources" / "skill_vault" / "_active_snapshot" / "video-to-skill",
    ROOT / "03_Resources" / "skill_vault" / "creative" / "video-to-skill",
]


def tracked_files(root: Path) -> set[Path]:
    ignored = {".venv", "__pycache__"}
    return {
        path.relative_to(root)
        for path in root.rglob("*")
        if path.is_file() and not any(part in ignored for part in path.parts)
    }


class MirrorParityTests(unittest.TestCase):
    def test_skill_mirrors_are_byte_identical(self):
        source_files = tracked_files(SOURCE)
        for mirror in MIRRORS:
            self.assertEqual(source_files, tracked_files(mirror), f"file set drift in {mirror}")
            for relative in sorted(source_files):
                self.assertEqual(
                    (SOURCE / relative).read_bytes(),
                    (mirror / relative).read_bytes(),
                    f"byte drift in {mirror / relative}",
                )


if __name__ == "__main__":
    unittest.main()

import importlib.util
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "workflow_sop.py"
SPEC = importlib.util.spec_from_file_location("workflow_sop", MODULE_PATH)
workflow_sop = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(workflow_sop)


def fake_ffprobe_runner(command, **_kwargs):
    payload = {
        "format": {"duration": "78.816", "size": "12", "format_name": "mov,mp4"},
        "streams": [{"codec_type": "video", "width": 1920, "height": 1128, "codec_name": "h264"}],
    }
    return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")


def fake_extractor_runner(command, **_kwargs):
    return subprocess.CompletedProcess(
        command,
        0,
        stdout=json.dumps(
            {
                "schema_version": 1,
                "segment_summary": "Opened a quote form.",
                "observations": [
                    {
                        "observation_id": "obs-1",
                        "timestamp_seconds": 1,
                        "action": "Open quote",
                        "evidence_type": "video_visible",
                        "evidence_status": "observed",
                        "confidence": "high",
                    }
                ],
                "open_questions": [],
            }
        ),
        stderr="",
    )


class WorkflowSopTests(unittest.TestCase):
    def test_segments_cover_full_duration_with_overlap(self):
        duration = 78 * 60 + 49
        segments = workflow_sop.make_segments(duration, segment_seconds=20 * 60, overlap_seconds=5)

        self.assertEqual(segments[0]["core_start_seconds"], 0)
        self.assertEqual(segments[-1]["core_end_seconds"], duration)
        for previous, current in zip(segments, segments[1:]):
            self.assertEqual(previous["core_end_seconds"], current["core_start_seconds"])
            self.assertLessEqual(current["media_start_seconds"], current["core_start_seconds"])
            self.assertGreaterEqual(previous["media_end_seconds"], previous["core_end_seconds"])

    def test_segment_boundaries_reject_invalid_values(self):
        with self.assertRaises(workflow_sop.WorkflowSopError):
            workflow_sop.make_segments(0)
        with self.assertRaises(workflow_sop.WorkflowSopError):
            workflow_sop.make_segments(10, segment_seconds=0)
        with self.assertRaises(workflow_sop.WorkflowSopError):
            workflow_sop.make_segments(10, segment_seconds=10, overlap_seconds=10)

    def test_fenced_segment_json_is_normalized_without_losing_unknowns(self):
        payload = workflow_sop.parse_segment_response(
            "```json\n"
            + json.dumps({"observations": [{"action": "Open quote", "unknowns": ["Who approves?"]}]})
            + "\n```"
        )
        observation = payload["observations"][0]
        self.assertEqual(observation["action"], "Open quote")
        self.assertEqual(observation["evidence_status"], "uncertain")
        self.assertEqual(observation["unknowns"], ["Who approves?"])
        self.assertEqual(observation["observation_id"], "observation-0001")

    def test_source_packet_records_hashes_and_restrictive_directories(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "demo.mp4"
            transcript = root / "transcript.md"
            video.write_bytes(b"not-a-real-video-fixture")
            transcript.write_text("Transcript text", encoding="utf-8")
            run_dir = root / "run"

            workflow_sop.create_source_packet(
                video=video,
                transcript=transcript,
                run_dir=run_dir,
                client="Example Client",
                workflow="Quoting",
                runner=fake_ffprobe_runner,
            )
            manifest = workflow_sop.load_manifest(run_dir)
            self.assertEqual(manifest["inputs"]["video"]["sha256"], workflow_sop.sha256_file(video))
            self.assertTrue(manifest["inputs"]["transcript"]["packet_path"])
            self.assertFalse(manifest["privacy"]["provider_approved"])
            self.assertEqual(stat.S_IMODE(os.stat(run_dir).st_mode), 0o700)
            self.assertEqual((run_dir / ".gitignore").read_text(encoding="utf-8"), "segments/\nraw/\nevidence/\n*.mp4\n")

    def test_extract_requires_explicit_provider_approval(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "demo.mp4"
            video.write_bytes(b"fixture")
            run_dir = root / "run"
            workflow_sop.create_source_packet(video=video, run_dir=run_dir, runner=fake_ffprobe_runner)

            with self.assertRaisesRegex(workflow_sop.WorkflowSopError, "Provider approval"):
                workflow_sop.extract_segments(run_dir, runner=lambda *_args, **_kwargs: None)

    def test_successful_extraction_is_resumable_by_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "demo.mp4"
            video.write_bytes(b"fixture")
            run_dir = root / "run"
            workflow_sop.create_source_packet(video=video, run_dir=run_dir, runner=fake_ffprobe_runner)
            manifest = workflow_sop.load_manifest(run_dir)
            manifest["segments"][0]["status"] = "materialized"
            manifest["segments"][0]["path"] = "segments/seg-0001.mp4"
            (run_dir / "segments" / "seg-0001.mp4").write_bytes(b"clip")
            workflow_sop.save_manifest(run_dir, manifest)

            calls = []

            def counting_runner(command, **kwargs):
                calls.append(command)
                return fake_extractor_runner(command, **kwargs)

            first = workflow_sop.extract_segments(run_dir, provider_approved=True, runner=counting_runner)
            second = workflow_sop.extract_segments(run_dir, provider_approved=True, runner=counting_runner)
            self.assertEqual(first["segments"][0]["status"], "success")
            self.assertEqual(second["segments"][0]["status"], "success")
            self.assertEqual(len(calls), 1)
            self.assertTrue((run_dir / "evidence" / "seg-0001.json").exists())

    def test_provider_cleanup_failure_keeps_segment_partial(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "demo.mp4"
            video.write_bytes(b"fixture")
            run_dir = root / "run"
            workflow_sop.create_source_packet(video=video, run_dir=run_dir, runner=fake_ffprobe_runner)
            manifest = workflow_sop.load_manifest(run_dir)
            manifest["segments"][0]["status"] = "materialized"
            manifest["segments"][0]["path"] = "segments/seg-0001.mp4"
            (run_dir / "segments" / "seg-0001.mp4").write_bytes(b"clip")
            workflow_sop.save_manifest(run_dir, manifest)

            def cleanup_failure_runner(command, **_kwargs):
                result = fake_extractor_runner(command)
                payload = json.loads(result.stdout)
                payload["cleanup_error"] = "provider refused delete"
                result.stdout = json.dumps(payload)
                return result

            result = workflow_sop.extract_segments(
                run_dir,
                provider_approved=True,
                runner=cleanup_failure_runner,
            )
            self.assertEqual(result["segments"][0]["status"], "failed")
            self.assertEqual(result["coverage"]["failed_segments"], 1)

    def test_compile_puts_questions_before_detail(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "demo.mp4"
            video.write_bytes(b"fixture")
            run_dir = root / "run"
            workflow_sop.create_source_packet(
                video=video,
                run_dir=run_dir,
                workflow="Quoting",
                runner=fake_ffprobe_runner,
            )
            manifest = workflow_sop.load_manifest(run_dir)
            segment = manifest["segments"][0]
            segment["status"] = "success"
            segment["evidence_path"] = "evidence/seg-0001.json"
            (run_dir / "evidence" / "seg-0001.json").write_text(
                json.dumps(
                    {
                        "segment_id": "seg-0001",
                        "media_start_seconds": 0,
                        "media_end_seconds": 78.816,
                        "observations": [
                            {
                                "observation_id": "seg-0001-observation-0001",
                                "timestamp_seconds": 2,
                                "absolute_timestamp_seconds": 2,
                                "action": "Open quote",
                                "system": "CRM",
                                "visible_state": "Quote form",
                                "evidence_status": "observed",
                                "evidence_type": "video_visible",
                                "confidence": "high",
                                "source_references": ["video:0-78.816"],
                                "unknowns": ["Which quote type is required?"]
                            }
                        ],
                        "open_questions": []
                    }
                ),
                encoding="utf-8",
            )
            workflow_sop.update_coverage(manifest)
            workflow_sop.save_manifest(run_dir, manifest)
            output = workflow_sop.compile_sop(run_dir)
            text = output.read_text(encoding="utf-8")

            self.assertIn("status: complete", text)
            self.assertLess(text.index("## Current-state workflow outline"), text.index("## Verification questions for the client"))
            self.assertLess(text.index("## Verification questions for the client"), text.index("## Detailed extraction and source evidence"))
            self.assertIn("Which quote type is required?", text)

    def test_credential_like_content_blocks_compilation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "demo.mp4"
            video.write_bytes(b"fixture")
            run_dir = root / "run"
            workflow_sop.create_source_packet(video=video, run_dir=run_dir, runner=fake_ffprobe_runner)
            manifest = workflow_sop.load_manifest(run_dir)
            segment = manifest["segments"][0]
            segment["status"] = "success"
            segment["evidence_path"] = "evidence/seg-0001.json"
            (run_dir / "evidence" / "seg-0001.json").write_text(
                json.dumps({"segment_id": "seg-0001", "observations": [{"action": "password=supersecretvalue"}]}),
                encoding="utf-8",
            )
            workflow_sop.update_coverage(manifest)
            workflow_sop.save_manifest(run_dir, manifest)
            with self.assertRaisesRegex(workflow_sop.WorkflowSopError, "credential-like"):
                workflow_sop.compile_sop(run_dir)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Prepare, resume, and compile video-based workflow-SOP source packets.

The packet is intentionally provider-neutral.  Gemini extraction is invoked
through ``gemini_video.py`` so this helper can own the durable local lifecycle
without importing a provider SDK or requiring credentials in tests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence


SCHEMA_VERSION = 1
DEFAULT_SEGMENT_SECONDS = 20 * 60
DEFAULT_OVERLAP_SECONDS = 5.0
SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".avi"}
SOURCE_PRECEDENCE = {
    "video": "visible behavior and sequence",
    "transcript": "spoken detail, roles, and exact terminology",
    "notes": "meeting context, decisions, and follow-up context",
}
EVIDENCE_TYPES = {"video_visible", "spoken", "inferred", "uncertain"}
EVIDENCE_STATUSES = {"observed", "spoken", "inferred", "uncertain"}
CONFIDENCE_LEVELS = {"high", "medium", "low"}
SENSITIVE_PATTERNS = (
    ("google-api-key", re.compile(r"AIza[0-9A-Za-z_-]{20,}")),
    ("openai-api-key", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
    ("bearer-token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{20,}")),
    (
        "credential-assignment",
        re.compile(r"(?i)\b(?:api[_ -]?key|secret|password|token)\b\s*[:=]\s*[^\s,;]{8,}"),
    ),
)


class WorkflowSopError(RuntimeError):
    """An actionable source-packet or workflow-SOP error."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify(value: str, fallback: str = "workflow-sop") -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (value[:60] or fallback).strip("-")


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path, kind: str) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.exists() or not path.is_file():
        raise WorkflowSopError(f"{kind} file not found or is not a file: {path}")
    return {
        "kind": kind,
        "path": str(path),
        "filename": path.name,
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "mime_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
    }


def sensitive_markers(text: str) -> list[str]:
    """Return labels only; never copy a matched secret into the manifest."""

    return [label for label, pattern in SENSITIVE_PATTERNS if pattern.search(text)]


def _secure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass


def _run_process(
    command: Sequence[str],
    *,
    capture_output: bool = True,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        capture_output=capture_output,
        text=True,
        check=check,
    )


def probe_media(
    video_path: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = _run_process,
) -> dict[str, Any]:
    """Return authoritative local media metadata from ffprobe."""

    video_path = video_path.expanduser().resolve()
    command = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(video_path),
    ]
    result = runner(command, capture_output=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown ffprobe error").strip()
        raise WorkflowSopError(f"ffprobe could not read {video_path.name}: {detail}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise WorkflowSopError("ffprobe returned invalid JSON") from exc

    format_data = payload.get("format", {})
    try:
        duration = float(format_data.get("duration", 0))
    except (TypeError, ValueError) as exc:
        raise WorkflowSopError("ffprobe did not provide a numeric duration") from exc
    if duration <= 0:
        raise WorkflowSopError("Video duration must be greater than zero")

    video_stream = next(
        (stream for stream in payload.get("streams", []) if stream.get("codec_type") == "video"),
        {},
    )
    return {
        "duration_seconds": duration,
        "duration_display": format_timestamp(duration),
        "width": video_stream.get("width"),
        "height": video_stream.get("height"),
        "video_codec": video_stream.get("codec_name"),
        "frame_rate": video_stream.get("r_frame_rate"),
        "format_name": format_data.get("format_name"),
        "size_bytes": int(format_data.get("size", video_path.stat().st_size) or 0),
    }


def make_segments(
    duration_seconds: float,
    *,
    segment_seconds: float = DEFAULT_SEGMENT_SECONDS,
    overlap_seconds: float = DEFAULT_OVERLAP_SECONDS,
) -> list[dict[str, Any]]:
    """Create ordered core intervals and overlapping media intervals."""

    if duration_seconds <= 0:
        raise WorkflowSopError("Duration must be greater than zero")
    if segment_seconds <= 0:
        raise WorkflowSopError("segment_seconds must be greater than zero")
    if overlap_seconds < 0 or overlap_seconds >= segment_seconds:
        raise WorkflowSopError("overlap_seconds must be non-negative and smaller than segment_seconds")

    segments: list[dict[str, Any]] = []
    core_start = 0.0
    index = 1
    epsilon = 1e-9
    while core_start < duration_seconds - epsilon:
        core_end = min(duration_seconds, core_start + segment_seconds)
        media_start = max(0.0, core_start - overlap_seconds)
        media_end = min(duration_seconds, core_end + overlap_seconds)
        segments.append(
            {
                "id": f"seg-{index:04d}",
                "core_start_seconds": round(core_start, 3),
                "core_end_seconds": round(core_end, 3),
                "media_start_seconds": round(media_start, 3),
                "media_end_seconds": round(media_end, 3),
                "media_duration_seconds": round(media_end - media_start, 3),
                "status": "pending",
                "attempts": 0,
            }
        )
        core_start = core_end
        index += 1
    return segments


def format_timestamp(seconds: float | int | None) -> str:
    if seconds is None:
        return "unknown"
    total = max(0, int(round(float(seconds))))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def load_manifest(run_dir: Path) -> dict[str, Any]:
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise WorkflowSopError(f"Manifest not found: {manifest_path}")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WorkflowSopError(f"Manifest is not valid JSON: {manifest_path}") from exc
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise WorkflowSopError(f"Unsupported manifest schema: {payload.get('schema_version')}")
    return payload


def save_manifest(run_dir: Path, manifest: Mapping[str, Any]) -> None:
    _atomic_write_json(run_dir / "manifest.json", manifest)


def _copy_text_source(path: Path, kind: str, sources_dir: Path) -> dict[str, Any]:
    record = file_record(path, kind)
    target = sources_dir / f"{slugify(kind)}-{slugify(path.stem)}{path.suffix.lower() or '.txt'}"
    shutil.copy2(path, target)
    record["packet_path"] = str(target.relative_to(sources_dir.parent))
    record["packet_sha256"] = sha256_file(target)
    return record


def create_source_packet(
    *,
    video: Path,
    run_dir: Path,
    transcript: Path | None = None,
    notes: Path | None = None,
    context: Iterable[Path] = (),
    client: str = "",
    workflow: str = "",
    segment_seconds: float = DEFAULT_SEGMENT_SECONDS,
    overlap_seconds: float = DEFAULT_OVERLAP_SECONDS,
    model: str = "gemini-3.5-flash",
    provider: str = "google",
    data_classification: str = "client-confidential",
    runner: Callable[..., subprocess.CompletedProcess[str]] = _run_process,
) -> Path:
    """Create a new durable packet and return its run directory."""

    video = video.expanduser().resolve()
    if not video.exists() or not video.is_file():
        raise WorkflowSopError(f"Video file not found or is not a file: {video}")
    if video.suffix.lower() not in SUPPORTED_VIDEO_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_VIDEO_EXTENSIONS))
        raise WorkflowSopError(f"Unsupported video extension {video.suffix!r}; expected one of {supported}")

    run_dir = run_dir.expanduser().resolve()
    if (run_dir / "manifest.json").exists():
        raise WorkflowSopError(f"A manifest already exists at {run_dir}; use resume/status or choose a new directory")
    media = probe_media(video, runner=runner)
    run_dir.mkdir(parents=True, exist_ok=False)
    _secure_directory(run_dir)
    sources_dir = run_dir / "sources"
    for directory in (run_dir / "segments", run_dir / "evidence", run_dir / "raw", sources_dir):
        _secure_directory(directory)
    (run_dir / ".gitignore").write_text("segments/\nraw/\nevidence/\n*.mp4\n", encoding="utf-8")

    sources: dict[str, Any] = {"video": file_record(video, "video")}
    if transcript:
        sources["transcript"] = _copy_text_source(transcript.expanduser().resolve(), "transcript", sources_dir)
    if notes:
        sources["notes"] = _copy_text_source(notes.expanduser().resolve(), "notes", sources_dir)
    context_records = []
    for context_path in context:
        context_records.append(_copy_text_source(context_path.expanduser().resolve(), "context", sources_dir))
    if context_records:
        sources["context"] = context_records

    run_id = run_dir.name
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "status": "planned",
        "client": client,
        "workflow": workflow,
        "inputs": sources,
        "media": media,
        "configuration": {
            "provider": provider,
            "model": model,
            "segment_seconds": segment_seconds,
            "overlap_seconds": overlap_seconds,
            "source_precedence": SOURCE_PRECEDENCE,
            "transport": "local_overlapping_clips_with_ephemeral_provider_uploads",
        },
        "privacy": {
            "data_classification": data_classification,
            "provider_approved": False,
            "approval_method": None,
            "raw_artifacts": "local-confidential",
        },
        "segments": make_segments(
            media["duration_seconds"],
            segment_seconds=segment_seconds,
            overlap_seconds=overlap_seconds,
        ),
        "coverage": {
            "duration_seconds": media["duration_seconds"],
            "covered_core_seconds": 0.0,
            "successful_segments": 0,
            "failed_segments": 0,
            "pending_segments": 0,
            "complete": False,
        },
        "errors": [],
        "outputs": {},
    }
    identity_material = {
        "video_sha256": sources["video"]["sha256"],
        "transcript_sha256": sources.get("transcript", {}).get("sha256"),
        "notes_sha256": sources.get("notes", {}).get("sha256"),
        "configuration": manifest["configuration"],
    }
    manifest["packet_identity"] = hashlib.sha256(
        json.dumps(identity_material, sort_keys=True).encode("utf-8")
    ).hexdigest()
    update_coverage(manifest)
    save_manifest(run_dir, manifest)
    return run_dir


def update_coverage(manifest: dict[str, Any]) -> dict[str, Any]:
    segments = manifest.get("segments", [])
    successful = [segment for segment in segments if segment.get("status") == "success"]
    failed = [segment for segment in segments if segment.get("status") == "failed"]
    pending = [segment for segment in segments if segment.get("status") not in {"success", "failed"}]
    manifest["coverage"] = {
        "duration_seconds": manifest.get("media", {}).get("duration_seconds"),
        "covered_core_seconds": round(sum(
            float(segment.get("core_end_seconds", 0)) - float(segment.get("core_start_seconds", 0))
            for segment in successful
        ), 3),
        "successful_segments": len(successful),
        "failed_segments": len(failed),
        "pending_segments": len(pending),
        "complete": bool(segments) and len(successful) == len(segments),
    }
    if manifest.get("status") not in {"compiled", "exported"}:
        if manifest["coverage"]["complete"]:
            manifest["status"] = "complete"
        elif failed:
            manifest["status"] = "partial"
        elif successful:
            manifest["status"] = "processing"
    manifest["updated_at"] = utc_now()
    return manifest


def verify_source_identity(manifest: Mapping[str, Any]) -> None:
    video_record = manifest.get("inputs", {}).get("video", {})
    video_path = Path(str(video_record.get("path", "")))
    if not video_path.exists():
        raise WorkflowSopError(f"Source video no longer exists: {video_path}")
    current_hash = sha256_file(video_path)
    if current_hash != video_record.get("sha256"):
        raise WorkflowSopError("Source video hash changed since packet planning; create a new packet instead of resuming")


def materialize_segments(
    run_dir: Path,
    *,
    retry_failed: bool = False,
    runner: Callable[..., subprocess.CompletedProcess[str]] = _run_process,
) -> dict[str, Any]:
    manifest = load_manifest(run_dir)
    verify_source_identity(manifest)
    video_path = Path(manifest["inputs"]["video"]["path"])
    manifest["status"] = "processing"
    for segment in manifest["segments"]:
        if segment.get("status") == "success":
            continue
        if segment.get("status") == "materialized" and (run_dir / segment.get("path", "")).is_file():
            continue
        if segment.get("status") == "failed" and not retry_failed:
            continue
        output_path = run_dir / "segments" / f"{segment['id']}.mp4"
        duration = float(segment["media_end_seconds"]) - float(segment["media_start_seconds"])
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            str(segment["media_start_seconds"]),
            "-i",
            str(video_path),
            "-t",
            str(duration),
            "-map",
            "0",
            "-c",
            "copy",
            "-avoid_negative_ts",
            "make_zero",
            str(output_path),
        ]
        result = runner(command, capture_output=True, check=False)
        segment["attempts"] = int(segment.get("attempts", 0)) + 1
        if result.returncode != 0 or not output_path.exists():
            detail = (result.stderr or result.stdout or "ffmpeg did not create a segment").strip()
            segment["status"] = "failed"
            segment["error"] = detail
            manifest["errors"].append({"segment_id": segment["id"], "stage": "materialize", "error": detail})
        else:
            segment["path"] = str(output_path.relative_to(run_dir))
            segment["status"] = "materialized"
            segment.pop("error", None)
        update_coverage(manifest)
        save_manifest(run_dir, manifest)
    update_coverage(manifest)
    save_manifest(run_dir, manifest)
    return manifest


def _strip_json_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def parse_segment_response(text: str) -> dict[str, Any]:
    """Parse and minimally normalize a structured segment response."""

    try:
        payload = json.loads(_strip_json_fence(text))
    except json.JSONDecodeError as exc:
        raise WorkflowSopError(f"Gemini segment response was not valid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise WorkflowSopError("Gemini segment response must be a JSON object")
    if payload.get("schema_version") not in (None, SCHEMA_VERSION):
        raise WorkflowSopError(f"Unsupported Gemini evidence schema: {payload.get('schema_version')}")
    observations = payload.get("observations", [])
    if observations is None:
        observations = []
    if not isinstance(observations, list):
        raise WorkflowSopError("Gemini segment response 'observations' must be a list")
    normalized: list[dict[str, Any]] = []
    for observation in observations:
        if not isinstance(observation, dict):
            continue
        item = dict(observation)
        item.setdefault("observation_id", f"observation-{len(normalized) + 1:04d}")
        item.setdefault("timestamp_seconds", 0.0)
        item.setdefault("absolute_timestamp_seconds", item.get("timestamp_seconds", 0.0))
        item.setdefault("actor", "unknown")
        item.setdefault("system", "unknown")
        item.setdefault("action", "")
        item.setdefault("visible_state", "")
        item.setdefault("decision_or_rule", "")
        item.setdefault("evidence_type", "uncertain")
        item.setdefault("evidence_status", "uncertain")
        item.setdefault("confidence", "medium")
        item.setdefault("source_references", [])
        item.setdefault("unknowns", [])
        if item["evidence_type"] not in EVIDENCE_TYPES:
            item["evidence_type"] = "uncertain"
        if item["evidence_status"] not in EVIDENCE_STATUSES:
            item["evidence_status"] = "uncertain"
        if item["confidence"] not in CONFIDENCE_LEVELS:
            item["confidence"] = "medium"
        normalized.append(item)
    payload["observations"] = normalized
    payload.setdefault("open_questions", [])
    payload.setdefault("segment_summary", "")
    payload["schema_version"] = SCHEMA_VERSION
    return payload


def extract_segments(
    run_dir: Path,
    *,
    gemini_script: Path | None = None,
    model: str | None = None,
    retry_failed: bool = False,
    provider_approved: bool = False,
    runner: Callable[..., subprocess.CompletedProcess[str]] = _run_process,
) -> dict[str, Any]:
    """Run the segment extractor and persist raw plus normalized receipts."""

    manifest = load_manifest(run_dir)
    verify_source_identity(manifest)
    provider = manifest.get("configuration", {}).get("provider", "google")
    if provider != "google":
        raise WorkflowSopError(
            f"Provider {provider!r} is not implemented by the local workflow runner; select google explicitly"
        )
    if not provider_approved and not manifest.get("privacy", {}).get("provider_approved", False):
        raise WorkflowSopError("Provider approval is required before uploading client material; pass --provider-approved")
    manifest.setdefault("privacy", {})["provider_approved"] = True
    manifest["privacy"]["approval_method"] = "explicit-cli-flag"
    manifest["privacy"]["approved_at"] = utc_now()
    gemini_script = gemini_script or Path(__file__).with_name("gemini_video.py")
    selected_model = model or manifest["configuration"].get("model", "gemini-3.5-flash")
    manifest["configuration"]["model"] = selected_model
    extraction_identity = hashlib.sha256(
        f"{manifest.get('packet_identity', '')}:{provider}:{selected_model}".encode("utf-8")
    ).hexdigest()
    manifest["status"] = "processing"
    for segment in manifest["segments"]:
        if segment.get("status") == "success" and segment.get("extraction_identity") == extraction_identity:
            continue
        if segment.get("status") == "success":
            segment["status"] = "materialized"
        if segment.get("status") == "failed" and not retry_failed:
            continue
        segment_path = run_dir / segment.get("path", "")
        if not segment.get("path") or not segment_path.is_file():
            segment["status"] = "failed"
            segment["error"] = "Materialized segment is missing"
            manifest["errors"].append({"segment_id": segment["id"], "stage": "extract", "error": segment["error"]})
            update_coverage(manifest)
            save_manifest(run_dir, manifest)
            continue

        command = [
            sys.executable,
            str(gemini_script),
            str(segment_path),
            "segment",
            "--model",
            selected_model,
            "--segment-id",
            segment["id"],
            "--segment-start",
            str(segment["media_start_seconds"]),
            "--segment-end",
            str(segment["media_end_seconds"]),
        ]
        result = runner(command, capture_output=True, check=False)
        raw_text = result.stdout or ""
        raw_path = run_dir / "raw" / f"{segment['id']}.txt"
        raw_path.write_text(raw_text, encoding="utf-8")
        segment["attempts"] = int(segment.get("attempts", 0)) + 1
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "segment extraction failed").strip()
            segment["status"] = "failed"
            segment["error"] = detail
            manifest["errors"].append({"segment_id": segment["id"], "stage": "extract", "error": detail})
        elif (markers := sensitive_markers(raw_text)):
            segment["status"] = "failed"
            segment["error"] = "Credential-like content requires manual review before normalization"
            segment["security_findings"] = markers
            manifest["errors"].append(
                {
                    "segment_id": segment["id"],
                    "stage": "security-review",
                    "error": segment["error"],
                    "markers": markers,
                }
            )
        else:
            try:
                evidence = parse_segment_response(raw_text)
            except WorkflowSopError as exc:
                segment["status"] = "failed"
                segment["error"] = str(exc)
                manifest["errors"].append({"segment_id": segment["id"], "stage": "parse", "error": str(exc)})
            else:
                if evidence.get("cleanup_error"):
                    segment["status"] = "failed"
                    segment["error"] = "Temporary provider file cleanup failed; manual retention review is required"
                    segment["cleanup_status"] = "failed"
                    manifest["errors"].append(
                        {
                            "segment_id": segment["id"],
                            "stage": "cleanup",
                            "error": segment["error"],
                        }
                    )
                    update_coverage(manifest)
                    save_manifest(run_dir, manifest)
                    continue
                for index, observation in enumerate(evidence.get("observations", []), start=1):
                    timestamp = observation.get("timestamp_seconds", 0.0)
                    try:
                        timestamp = float(timestamp)
                    except (TypeError, ValueError):
                        timestamp = 0.0
                    observation["timestamp_seconds"] = timestamp
                    absolute_timestamp = observation.get("absolute_timestamp_seconds")
                    if not isinstance(absolute_timestamp, (int, float)) or absolute_timestamp == timestamp:
                        absolute_timestamp = segment["media_start_seconds"] + timestamp
                    observation["absolute_timestamp_seconds"] = float(absolute_timestamp)
                    observation.setdefault(
                        "observation_id", f"{segment['id']}-observation-{index:04d}"
                    )
                    observation.setdefault(
                        "source_references",
                        [
                            f"video:{segment['media_start_seconds']}-{segment['media_end_seconds']}"
                        ],
                    )
                evidence.update(
                    {
                        "segment_id": segment["id"],
                        "media_start_seconds": segment["media_start_seconds"],
                        "media_end_seconds": segment["media_end_seconds"],
                        "core_start_seconds": segment["core_start_seconds"],
                        "core_end_seconds": segment["core_end_seconds"],
                        "model": selected_model,
                        "transport": "ephemeral_gemini_file_api_upload",
                    }
                )
                _atomic_write_json(run_dir / "evidence" / f"{segment['id']}.json", evidence)
                segment["evidence_path"] = str(Path("evidence") / f"{segment['id']}.json")
                segment["extraction_identity"] = extraction_identity
                segment["status"] = "success"
                segment.pop("error", None)
        update_coverage(manifest)
        save_manifest(run_dir, manifest)
    update_coverage(manifest)
    save_manifest(run_dir, manifest)
    return manifest


def _read_packet_sources(manifest: Mapping[str, Any], run_dir: Path) -> dict[str, str]:
    sources: dict[str, str] = {}
    for kind in ("transcript", "notes"):
        record = manifest.get("inputs", {}).get(kind)
        if isinstance(record, Mapping) and record.get("packet_path"):
            path = run_dir / str(record["packet_path"])
            if path.exists():
                sources[kind] = path.read_text(encoding="utf-8", errors="replace")
    return sources


def _load_evidence(run_dir: Path, manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for segment in manifest.get("segments", []):
        evidence_path = segment.get("evidence_path")
        if not evidence_path:
            continue
        path = run_dir / str(evidence_path)
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                evidence.append(payload)
    return evidence


def _observation_text(observation: Mapping[str, Any]) -> str:
    action = str(observation.get("action") or "Observed workflow action")
    visible = str(observation.get("visible_state") or "")
    system = str(observation.get("system") or "")
    suffix = " — ".join(part for part in (system, visible) if part)
    return f"{action}{f' ({suffix})' if suffix else ''}"


def _observation_timestamp(packet: Mapping[str, Any], observation: Mapping[str, Any]) -> float | None:
    value = observation.get("absolute_timestamp_seconds")
    if isinstance(value, (int, float)):
        return float(value)
    value = observation.get("timestamp_seconds")
    if isinstance(value, (int, float)):
        return float(packet.get("media_start_seconds", 0)) + float(value)
    return None


def _dedupe_observations(
    observations: Iterable[tuple[dict[str, Any], dict[str, Any]]],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    seen: set[tuple[Any, ...]] = set()
    deduped: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for packet, observation in observations:
        timestamp = _observation_timestamp(packet, observation)
        action = re.sub(r"\s+", " ", str(observation.get("action", "")).strip().lower())
        key = (round(timestamp, 1) if timestamp is not None else None, action)
        if key in seen and action:
            continue
        seen.add(key)
        deduped.append((packet, observation))
    return deduped


def compile_sop(
    run_dir: Path,
    *,
    output: Path | None = None,
    title: str | None = None,
    allow_sensitive_output: bool = False,
) -> Path:
    """Compile a deterministic client-review draft from packet evidence."""

    manifest = load_manifest(run_dir)
    update_coverage(manifest)
    save_manifest(run_dir, manifest)
    evidence = _load_evidence(run_dir, manifest)
    sources = _read_packet_sources(manifest, run_dir)
    complete = bool(manifest["coverage"].get("complete"))
    status = "complete" if complete else "draft-partial"
    client = manifest.get("client") or "Client"
    workflow = manifest.get("workflow") or "Workflow"
    document_title = title or f"{client} — {workflow} Workflow SOP"
    questions: list[str] = []
    if not sources.get("transcript"):
        questions.append("Please provide or confirm the transcript if speaker wording, roles, or exact terminology matter.")
    if not sources.get("notes"):
        questions.append("Please confirm any meeting decisions or context that are not visible in the recording.")
    for segment in manifest.get("segments", []):
        if segment.get("status") != "success":
            questions.append(
                f"What should happen in the uncovered interval {format_timestamp(segment.get('core_start_seconds'))}–{format_timestamp(segment.get('core_end_seconds'))}?"
            )
    observations: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for packet in evidence:
        for observation in packet.get("observations", []):
            if isinstance(observation, dict):
                observations.append((packet, observation))
                for unknown in observation.get("unknowns", []) or []:
                    questions.append(str(unknown))
        for question in packet.get("open_questions", []) or []:
            questions.append(str(question))
    observations = _dedupe_observations(observations)

    lines = [
        "---",
        f"title: {json.dumps(document_title, ensure_ascii=False)}",
        f"client: {json.dumps(client, ensure_ascii=False)}",
        f"workflow: {json.dumps(workflow, ensure_ascii=False)}",
        f"status: {status}",
        f"source_packet: {json.dumps(manifest.get('run_id', run_dir.name), ensure_ascii=False)}",
        f"generated: {json.dumps(utc_now(), ensure_ascii=False)}",
        "tags: [sop, workflow-mapping, client-verification]",
        "---",
        "",
        f"# {document_title}",
        "",
        f"> Draft for client verification. Current evidence status: **{status}**.",
        "> Please add, remove, or correct items directly in the outline and answer the questions before automation is specified.",
        "",
        "## Workflow purpose and scope",
        "",
        f"This draft maps the current-state **{workflow}** workflow from a recorded demonstration. It is intended to capture what happens today, not to prescribe a future automated design.",
        "",
        "## Current-state workflow outline",
        "",
    ]
    if observations:
        for index, (packet, observation) in enumerate(observations, start=1):
            timestamp = _observation_timestamp(packet, observation)
            lines.append(f"{index}. **{_observation_text(observation)}** — [video {format_timestamp(timestamp)}]")
    else:
        lines.append("1. [Add or remove steps after reviewing the detailed evidence below.]")

    deduped_questions = list(dict.fromkeys(question.strip() for question in questions if question.strip()))
    lines.extend(["", "## Verification questions for the client", ""])
    if deduped_questions:
        lines.extend(f"- [ ] {question}" for question in deduped_questions)
    else:
        lines.append("- [ ] Confirm that the outline above accurately represents the demonstrated current state.")

    lines.extend(["", "## Detailed extraction and source evidence", ""])
    if evidence:
        for packet in evidence:
            segment_id = packet.get("segment_id", "unknown segment")
            start = packet.get("media_start_seconds")
            end = packet.get("media_end_seconds")
            lines.extend([
                f"### {segment_id} ({format_timestamp(start)}–{format_timestamp(end)})",
                "",
                f"**Segment summary:** {packet.get('segment_summary') or 'No segment summary provided.'}",
                "",
            ])
            for observation in packet.get("observations", []):
                if not isinstance(observation, dict):
                    continue
                timestamp = _observation_timestamp(packet, observation)
                lines.extend([
                    f"- **{format_timestamp(timestamp)} — {_observation_text(observation)}**",
                    f"  - Evidence status: `{observation.get('evidence_status', 'uncertain')}`; confidence: `{observation.get('confidence', 'medium')}`.",
                ])
                if observation.get("decision_or_rule"):
                    lines.append(f"  - Decision/rule: {observation['decision_or_rule']}")
                if observation.get("unknowns"):
                    lines.append(f"  - Needs client verification: {'; '.join(map(str, observation['unknowns']))}")
                if observation.get("source_references"):
                    lines.append(f"  - Source references: {'; '.join(map(str, observation['source_references']))}")
    else:
        lines.append("No normalized segment evidence is available yet. Run segment extraction, then compile again.")

    lines.extend([
        "",
        "## Automation-relevant observations",
        "",
        "- Candidate systems, inputs, decisions, handoffs, and exception paths should be confirmed against the detailed evidence before they become implementation requirements.",
        "- This section is intentionally provisional until the client verifies the current-state outline and questions above.",
        "",
        "## Source and confidence notes",
        "",
        "- Video is authoritative for visible behavior and sequence.",
        "- Transcript is authoritative for spoken detail, roles, and exact terminology.",
        "- Granola/meeting notes provide context and decisions; disagreements are verification questions.",
        f"- Packet coverage: {manifest['coverage']['successful_segments']} successful, {manifest['coverage']['failed_segments']} failed, {manifest['coverage']['pending_segments']} pending segment(s).",
        "- Claims that are inferred, unclear, or unsupported are not settled requirements.",
    ])

    output = output or (run_dir / f"{slugify(workflow)}-workflow-sop.md")
    output = output.expanduser().resolve()
    if not allow_sensitive_output and (markers := sensitive_markers("\n".join(lines))):
        raise WorkflowSopError(
            "Potential credential-like content detected in the draft "
            f"({', '.join(markers)}); review manually or pass --allow-sensitive-output"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    manifest["outputs"]["markdown"] = str(output.relative_to(run_dir)) if output.is_relative_to(run_dir) else str(output)
    manifest["status"] = "compiled" if complete else "partial"
    manifest["updated_at"] = utc_now()
    save_manifest(run_dir, manifest)
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare and compile a resumable video workflow-SOP source packet.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="Measure a video and create a durable source packet")
    plan.add_argument("--video", type=Path, required=True)
    plan.add_argument("--run-dir", type=Path, required=True)
    plan.add_argument("--transcript", type=Path)
    plan.add_argument("--notes", type=Path)
    plan.add_argument("--context", type=Path, action="append", default=[])
    plan.add_argument("--client", default="")
    plan.add_argument("--workflow", default="")
    plan.add_argument("--segment-seconds", type=float, default=DEFAULT_SEGMENT_SECONDS)
    plan.add_argument("--overlap-seconds", type=float, default=DEFAULT_OVERLAP_SECONDS)
    plan.add_argument("--model", default="gemini-3.5-flash")
    plan.add_argument("--provider", default="google")
    plan.add_argument("--data-classification", default="client-confidential")

    materialize = subparsers.add_parser("materialize", help="Create bounded MP4 segment files from a packet")
    materialize.add_argument("--run-dir", type=Path, required=True)
    materialize.add_argument("--retry-failed", action="store_true")

    extract = subparsers.add_parser("extract", help="Run the Gemini segment extractor and persist receipts")
    extract.add_argument("--run-dir", type=Path, required=True)
    extract.add_argument("--gemini-script", type=Path)
    extract.add_argument("--model")
    extract.add_argument("--retry-failed", action="store_true")
    extract.add_argument("--provider-approved", action="store_true")

    compile_parser = subparsers.add_parser("compile", help="Compile a client-review Markdown draft")
    compile_parser.add_argument("--run-dir", type=Path, required=True)
    compile_parser.add_argument("--output", type=Path)
    compile_parser.add_argument("--title")
    compile_parser.add_argument("--allow-sensitive-output", action="store_true")

    status = subparsers.add_parser("status", help="Print packet status and coverage")
    status.add_argument("--run-dir", type=Path, required=True)

    validate = subparsers.add_parser("validate", help="Validate packet structure and coverage metadata")
    validate.add_argument("--run-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "plan":
            run_dir = create_source_packet(
                video=args.video,
                run_dir=args.run_dir,
                transcript=args.transcript,
                notes=args.notes,
                context=args.context,
                client=args.client,
                workflow=args.workflow,
                segment_seconds=args.segment_seconds,
                overlap_seconds=args.overlap_seconds,
                model=args.model,
                provider=args.provider,
                data_classification=args.data_classification,
            )
            print(run_dir)
        elif args.command == "materialize":
            manifest = materialize_segments(args.run_dir, retry_failed=args.retry_failed)
            print(json.dumps(manifest["coverage"], indent=2))
        elif args.command == "extract":
            manifest = extract_segments(
                args.run_dir,
                gemini_script=args.gemini_script,
                model=args.model,
                retry_failed=args.retry_failed,
                provider_approved=args.provider_approved,
            )
            print(json.dumps(manifest["coverage"], indent=2))
        elif args.command == "compile":
            print(
                compile_sop(
                    args.run_dir,
                    output=args.output,
                    title=args.title,
                    allow_sensitive_output=args.allow_sensitive_output,
                )
            )
        elif args.command == "status":
            manifest = load_manifest(args.run_dir)
            update_coverage(manifest)
            print(json.dumps({"run_id": manifest["run_id"], "status": manifest["status"], "coverage": manifest["coverage"]}, indent=2))
        elif args.command == "validate":
            manifest = load_manifest(args.run_dir)
            update_coverage(manifest)
            save_manifest(args.run_dir, manifest)
            if not manifest.get("segments"):
                raise WorkflowSopError("Manifest has no segments")
            print(json.dumps({"valid": True, "status": manifest["status"], "coverage": manifest["coverage"]}, indent=2))
        return 0
    except WorkflowSopError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

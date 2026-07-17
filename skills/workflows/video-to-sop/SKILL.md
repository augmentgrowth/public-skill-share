---
name: video-to-sop
description: >
  Extract SOPs and Claude Code skills from video recordings or YouTube tutorials.
  Watches a video via Gemini's video understanding API, extracts a phase-by-phase
  SOP with tacit knowledge and quality standards, and optionally converts the SOP
  into a full Claude Code skill. Triggers on: video to skill, video to SOP, turn
  this video into a skill, record to skill, screencast to SOP, extract process
  from video, /video-to-skill. Also triggers when the user shares a YouTube URL
  or local video path and wants to capture the process shown in it, or says things
  like "I recorded myself doing X, turn it into a skill", "watch this and write
  an SOP", "extract steps from this video", or "learn from this recording".
---

# Video-to-Skill

Turn any video into a structured SOP or a full Claude Code skill.

**Input:** YouTube URL, local video file, or supplied transcript/meeting notes
**Output:** Structured SOP (always) + Claude Code skill (optional)

## Choose the execution lane first

### Lane 1: Lightweight YouTube resource SOP

Use this lane when the user pastes a public YouTube URL and asks for an SOP in Resources, a reference SOP, or a Markdown note for personal reuse. If the request is clearly “YouTube + SOP in Resources,” automatically select Lane 1 without asking the user to choose an extraction or output mode.

Default behavior:

- Pull captions and video metadata with `yt-dlp`; prefer manual captions over auto-captions.
- Synthesize directly into one Markdown file in Resources, normally `03_Resources/SOPs/{YYYY-MM-DD}_{slug}_SOP.md` unless the user names another Resources path.
- Perform one focused content/structure check, then finish. Do not run the client-verification document workflow.
- Do not create a resumable workflow packet, split the recording into overlapping segments, generate verification-question/evidence appendices, render DOCX, convert to Google Docs, or upload to a client workspace unless the user explicitly asks.
- Use Gemini vision only when the SOP depends materially on visible UI actions, diagrams, settings, or demonstrations that captions cannot recover. When vision is needed, use the smallest sufficient pass; do not automatically inherit the multi-pass client workflow.

This lane optimizes for a useful knowledge artifact with low ceremony. Honest transcript gaps and source attribution still apply, but client discovery rigor does not.

### Lane 2: Client current-state workflow SOP

Use this lane for confidential or client-side walkthroughs that must reconstruct current operations, distinguish demonstrated behavior from proposed future state, support client verification, or produce polished collaborative deliverables. Lane 2 uses Workflow-SOP Mode below.

When routing is ambiguous, choose based on the requested artifact and evidence burden—not video length alone. A long public tutorial can still be Lane 1; a short client walkthrough can require Lane 2.

## Workflow-SOP Mode (Lane 2)

Use Workflow-SOP Mode when a client demo recording must be mapped into a current-state workflow that the client can verify before automation is designed. It is suitable for confidential operational walkthroughs and other AI-client workflows.

**Required inputs:**

- At least one primary source: a local MP4/MOV/WebM/MKV/AVI recording, a video URL, or a supplied transcript/meeting-note file
- Client/workflow name and a local output directory

**Recommended supplements:**

- Detailed transcript for spoken detail, roles, and exact terminology
- Granola or meeting notes for context, decisions, and follow-up items
- Optional chat/context files

The workflow is deliberately staged and resumable:

1. `workflow_sop.py plan` measures the local recording with `ffprobe`, hashes sources, and creates a durable run packet.
2. `workflow_sop.py materialize` creates bounded overlapping local clips that cover the full measured timeline.
3. `workflow_sop.py extract --provider-approved` runs Gemini's structured `segment` phase per clip. Approval is explicit because client recordings may be confidential.
4. `workflow_sop.py compile` creates a Markdown draft with the client-editable outline and verification questions first.
5. Optionally use `render_google_docx.sh` to create a conservative DOCX and validate a local Markdown round trip. Markdown remains canonical. To inherit an approved client style, prefix the command with `REFERENCE_DOCX="/path/to/approved-reference.docx"`; the renderer fails closed if that file is missing.

Example packet setup:

```bash
python3 "SKILL_DIR/scripts/workflow_sop.py" plan \
  --video "/path/to/recording.mp4" \
  --transcript "/path/to/transcript.md" \
  --notes "/path/to/granola-notes.md" \
  --client "Client Name" \
  --workflow "Workflow Name" \
  --run-dir "/path/to/output/workflow-sop-run"
python3 "SKILL_DIR/scripts/workflow_sop.py" materialize --run-dir "/path/to/output/workflow-sop-run"
python3 "SKILL_DIR/scripts/workflow_sop.py" extract --run-dir "/path/to/output/workflow-sop-run" --provider-approved
python3 "SKILL_DIR/scripts/workflow_sop.py" compile --run-dir "/path/to/output/workflow-sop-run"
```

**Source authority:** video is authoritative for visible behavior and sequence; transcript is authoritative for spoken detail, roles, and exact terminology; Granola/meeting notes provide context and decisions. Conflicts, missing steps, unsupported claims, and unclear screen states become verification questions. Never invent a business rule or present a partial packet as complete.

**Output order:** workflow purpose/scope → simple current-state outline → client verification questions → detailed timestamped evidence → provisional automation-relevant observations → source/confidence notes. This keeps the client-facing review simple while preserving detail at the bottom.

**Privacy and provider boundary:** the packet records data classification and local source hashes. Gemini is the primary provider for large local video; provider selection is explicit and there is no automatic OpenRouter fallback. Raw clips/responses stay in local, ignored packet directories. Workflow-SOP Mode does not upload to Google Drive, create a native Google Doc, or execute a client workflow.

**Vision routing and standing operator approval:** this installation has standing operator approval to use Gemini vision when visual evidence is material to reconstructing the workflow. If only a transcript is supplied, or the visible screen state is not important to the requested SOP, use the transcript-only path. When necessary video is referenced but not local, first try the named link, configured connector, or available local tooling before asking the operator to download it. The `--provider-approved` flag remains a fail-closed execution boundary; the standing approval satisfies that boundary unless a new data-handling constraint or provider change requires fresh approval.

### Multiple workstreams in one recording

When one recording covers several distinct workflows, create one durable run packet and extract the recording once. Reuse the normalized transcript and segment evidence to produce separate canonical SOPs for each workstream. Keep the SOPs independently usable, while recording shared evidence references rather than uploading, segmenting, or analyzing the same source more than once.

**Important:** this mode produces a draft-for-client-verification artifact. It does not automatically convert the workflow into a runnable Claude skill or automation spec.

## Prerequisites

Before running this skill, verify:

1. **GOOGLE_API_KEY** — Provide `GOOGLE_API_KEY` or `GEMINI_API_KEY` in the environment. If missing, get one at https://aistudio.google.com > Get API Key
2. **yt-dlp** — Required for YouTube URLs. Install: `brew install yt-dlp`
3. **Python 3** — Required for Gemini API script. The script auto-creates a venv on first run.
4. **ffmpeg** — Optional, used for compressing large videos. Install: `brew install ffmpeg`

Check prerequisites with:
```bash
echo "API_KEY: ${GOOGLE_API_KEY:+SET}" && which yt-dlp && which python3 && which ffmpeg
```

If GOOGLE_API_KEY is not set, stop and tell the user:
> You need a Google API key for Gemini. Go to https://aistudio.google.com, click "Get API Key" in the sidebar, create one, then add `GOOGLE_API_KEY=your_key` to your shell profile or run `export GOOGLE_API_KEY=your_key` in this session.

## Execution

### Phase 1: Parse Input

Extract from the user's message:
- **Video source**: YouTube URL (regex: `youtube\.com/watch|youtu\.be/|youtube\.com/shorts`) or local file path (extensions: `.mp4`, `.mov`, `.webm`, `.mkv`, `.avi`)
- **Process name**: What the video demonstrates (ask if not obvious)
- **Extraction mode**: Full vision (Gemini reads the video file directly) OR transcript-only (yt-dlp captions + description, no Gemini calls)
- **Output mode**: SOP only, or SOP + skill

Apply the lane router before asking extraction/output questions. A public YouTube URL plus an explicit request for an SOP in Resources automatically selects Lane 1 and SOP-only output. Skip the mode questions and proceed through the lightweight captions/metadata path unless visual evidence is material.

If no video or transcript source is provided, ask:
> Share a video URL, a local video file, or a transcript/meeting-note file. I'll extract the process into a structured SOP.

If a supplied transcript or meeting-note file is the only source, select the direct supplied-transcript route below. Do not request or download a video unless visible screen evidence is material to the requested result.

If the user has already stated an extraction or output preference (e.g., "transcript only", "skip vision", "make me a skill from this"), honor it and skip the corresponding AskUserQuestion below.

If the evidence need is genuinely ambiguous and no standing approval or preference resolves it, use AskUserQuestion to confirm **extraction mode**:
> How should I extract this video?
> 1. **Full Gemini vision** — Reads the video file directly. Catches on-screen prompts, UI flows, visual demos. Slower, costs Gemini API credit. Best for tutorials where the visual content matters.
> 2. **Transcript-only** — yt-dlp pulls captions + video description, then synthesizes. Faster, no API cost. Best for podcast-style/talking-head videos where speech is the primary signal, or when Gemini is unavailable.

Then use AskUserQuestion to confirm **output mode**:
> What do you want from this video?
> 1. **SOP only** — Structured procedure document I can reference later
> 2. **SOP + Skill** — Full Claude Code skill I can invoke to repeat this process

**Routing**: If extraction mode is `transcript-only`, skip Phases 2 (video download) and 4 (Gemini), and use the **Transcript-Only Path** described below instead. Phase 3 (validation) is also skipped — captions are tiny.

### Phase 2: Video Acquisition

**For YouTube URLs:**
```bash
mkdir -p /tmp/video-to-skill
yt-dlp -f "bestvideo[height<=720]+bestaudio/best[height<=720]" \
  --merge-output-format mp4 \
  --no-playlist \
  -o "/tmp/video-to-skill/%(title)s.%(ext)s" \
  "VIDEO_URL" 2>&1
```

Capture the output file path. If yt-dlp fails:
- Private/unavailable: Tell user to download manually and provide the file path
- Age-restricted: Try with `--cookies-from-browser chrome` flag
- Geo-blocked: Tell user to use a VPN and download manually

**For local files:** Verify the file exists and is a supported video format.

### Phase 3: Video Validation

Check file size:
```bash
ls -lh "VIDEO_PATH" | awk '{print $5}'
```

| Size | Action |
|------|--------|
| < 100MB | Proceed directly |
| 100MB - 500MB | Warn user it may take a few minutes |
| 500MB - 2GB | Attempt compression if ffmpeg available |
| > 2GB | Must compress or ask user to trim |

**Compression (if needed):**
```bash
ffmpeg -i "INPUT" -vf "scale=-2:720" -c:v libx264 -crf 28 -c:a aac -b:a 128k "/tmp/video-to-skill/compressed.mp4"
```

### Phase 4: Gemini Multi-Phase Extraction

The Python script at `scripts/gemini_video.py` handles video upload and Gemini querying.
Run 3 extraction phases sequentially. Each phase uploads the video to Gemini's File API, queries, then cleans up.

**Script location:** Relative to this skill file at `scripts/gemini_video.py`

**IMPORTANT:** Always use the venv python directly, not system python:
```bash
VENV_PY="SKILL_DIR/scripts/.venv/bin/python3"
```
If the venv doesn't exist yet (first run), use system python once — it will auto-create the venv. Then use the venv python for all subsequent calls.

**Phase 4a: Overview**
```bash
$VENV_PY "SKILL_DIR/scripts/gemini_video.py" "VIDEO_PATH" overview
```
Save output to a variable. This gives you: title, duration, summary, prerequisites, main phases, key outcomes.

**Phase 4b: Detailed Steps**
```bash
$VENV_PY "SKILL_DIR/scripts/gemini_video.py" "VIDEO_PATH" steps
```
Save output. This is the core SOP: phase-by-phase steps with actions, details, checkpoints, micro-decisions, hesitations.

**Phase 4c: Quality & Tacit Knowledge**
```bash
$VENV_PY "SKILL_DIR/scripts/gemini_video.py" "VIDEO_PATH" quality
```
Save output. This captures: quality standards, rejections, tacit knowledge, style references, edge cases.

**If any phase fails:**
- "GOOGLE_API_KEY" error: Tell user to set the key
- Upload failure: Check file size, try compression
- Processing failure: Video may be corrupted or unsupported format
- Thin/empty response: Re-run that phase with an explicitly selected current model from the Gemini model catalog; do not use the retired `gemini-3-pro` identifier.

---

### Transcript-Only Path (used when extraction mode = "transcript-only")

Replaces Phases 2-4. Use this when user opted out of Gemini vision, when `GOOGLE_API_KEY` is unavailable, or when video content is primarily speech (podcast, talking head).

**Direct supplied-transcript route:** When the user supplies a transcript or meeting-note file without a video or URL, read that file directly and begin at Step 4 (Synthesize). Skip video acquisition, `ffprobe`, segmentation, caption download, and Gemini. Record the supplied file path and hash as the source when Workflow-SOP provenance is required.

**Step 1: Download captions + metadata**
```bash
mkdir -p /tmp/video-to-skill
yt-dlp \
  --write-auto-sub --write-sub --sub-lang en --sub-format vtt \
  --skip-download \
  --write-info-json \
  -o "/tmp/video-to-skill/%(id)s.%(ext)s" \
  "VIDEO_URL"
```

If manual English captions exist (`*.en.vtt` not just `*.en.auto.vtt`), prefer them — they're cleaner than auto-generated.

**Step 2: Parse captions**
Strip VTT timestamps. Auto-subs repeat lines as they roll on screen — collapse to clean prose. Keep approximate minute-markers (every 60-120s) so the SOP can reference video position.

**Step 3: Parse info.json**
Pull: title, channel, description, duration, chapter markers, tags. The description and chapter markers are **ground truth** — treat them as more reliable than transcript ASR. If the host shows a prompt on screen but you can find the exact text in the description, use the description version.

**Step 4: Synthesize**
You (Claude) read the cleaned transcript + description and produce the three extraction phases (overview, steps, quality) directly — no Gemini API call. Follow the same output shape Gemini would produce.

**Step 5: Flag gaps honestly**
At the top of the SOP, add a clearly labeled note:
> **Extraction method**: Transcript + video description (Gemini vision not used — captures speech and description only).

Throughout the SOP, mark anything you couldn't capture with `[VISUAL-ONLY — needs vision re-extraction]` so future re-runs know exactly which sections to revisit.

**Quality rules (same as Gemini path)**
- No fabrication. Transcript gap → write "[transcript gap]" not invented content.
- Prefer host's exact words over paraphrase, especially for prompts and tool names.
- Use chapter markers as phase boundaries when present.

**ASR error patterns to watch for**
Common YouTube auto-sub errors: tool names get mistranscribed (e.g., "Seedance" → "Cance", "Veo" → "Video", "Higgsfield" → "Higgs Field"). Cross-check the description for the actual spelling.

---

### Phase 5: SOP Compilation

Combine all three Gemini responses into a single structured SOP document.

**Save location:** `03_Resources/SOPs/{YYYY-MM-DD}_{process-name}_SOP.md`

**Filename convention:** Always prefix the filename with the extraction date in `YYYY-MM-DD` format, followed by an underscore, then the process-name slug, then `_SOP.md`. The date is the day the SOP was extracted (same value used in the `extracted` frontmatter field). The process-name slug should be lowercase, hyphen-separated, and concise (≤60 chars). Examples:
- `2026-05-14_claude-code-rag-7-levels_SOP.md`
- `2026-05-14_agent-memory-architecture_SOP.md`

This date prefix is required regardless of `sop_location` override — applies anywhere SOPs are saved.

Use this template structure:

```markdown
---
title: "{Process Name} SOP"
source: "{video URL or file path}"
extracted: "{YYYY-MM-DD}"
tags: [sop, video-extracted]
---

# {Process Name} — Standard Operating Procedure

**Source**: {video URL or path}
**Extracted**: {date}
**Duration**: ~{approximate length}

## Prerequisites
{From overview extraction}

## Process Overview
{Summary from overview extraction}

## Phases

### Phase 1: {Title} ({timestamp range})

**Goal**: {what this phase accomplishes}

1. **{Step title}**
   - Action: {imperative instruction}
   - Details: {specific values, paths, settings}
   - Checkpoint: {what to verify before moving on}

{Continue for all phases from steps extraction}

## Nuances and Tacit Knowledge

### Micro-Decisions
{From quality extraction — small choices made without explanation}

### Hesitations and Corrections
{From steps extraction — moments of backtracking or correction}

### Implicit Assumptions
{From quality extraction — unstated prerequisites or context}

## Quality Standards

### What "Done Right" Looks Like
{From quality extraction}

### What Was Rejected
{From quality extraction — things tried and undone}

### Verification Steps
{How to confirm the output is correct}

## Style References
{From quality extraction — external examples or resources}

## Edge Cases and Warnings
{From quality extraction}
```

**CHECKPOINT:** Present a summary of the SOP to the user using AskUserQuestion:
> Here's what I extracted from the video:
> - **Process**: {name}
> - **Phases**: {count} phases, {total steps} steps
> - **Key nuances captured**: {2-3 highlights from tacit knowledge}
>
> The full SOP has been saved to `03_Resources/SOPs/{YYYY-MM-DD}_{name}_SOP.md`.
> Review it and let me know if anything looks off or needs correction.

If user chose **SOP only**, stop here.

### Phase 6: Skill Creation

Convert the SOP into a Claude Code skill. Use the official-skill-creator patterns for structure.

**Skill directory:** `.claude/skills/{skill-name}/`

**Conversion mapping:**
| SOP Section | Skill Section |
|-------------|---------------|
| Prerequisites | Prerequisites check in execution |
| Phases → Steps | Execution flow (numbered phases) |
| Quality Standards | Self-check criteria / verification |
| Tacit Knowledge | Principles and anti-patterns |
| Edge Cases | Error handling |
| Style References | Reference files |

**Steps:**
1. Derive a skill name from the process (lowercase, hyphenated)
2. Write trigger conditions based on what the process does
3. Convert SOP phases into skill execution phases
4. Add AskUserQuestion checkpoints where the original process had decision points
5. Include quality standards as verification steps
6. Save tacit knowledge as inline guidance comments

Create `SKILL.md` with proper frontmatter:
```yaml
---
name: {skill-name}
description: >
  {What the skill does, when to trigger it, example phrases}
---
```

**CHECKPOINT:** Present the draft skill to the user:
> I've converted the SOP into a skill at `.claude/skills/{name}/SKILL.md`.
> Key decisions:
> - **Triggers on**: {trigger phrases}
> - **{N} execution phases** with {M} human checkpoints
> - **Quality checks**: {list}
>
> Want me to adjust anything before finalizing?

### Cleanup

After successful extraction, clean up temporary files:
```bash
rm -rf /tmp/video-to-skill/
```

## Tips for Better Results

- **Longer recordings = richer skills.** 4 min = basic skill. 20 min = captures edge cases and judgment calls.
- **Talk while you work.** "I'm choosing this because..." is gold for tacit knowledge extraction.
- **Show your references.** Open the examples you're comparing against — Gemini captures them.
- **Don't clean up your process.** Backtracking and corrections ARE the skill. Messy > rehearsed.

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| model | gemini-3.5-flash | Default current model for the local helper. Override explicitly when a current Gemini model is required; do not use retired `gemini-3-pro` guidance. |
| sop_location | 03_Resources/SOPs/ | Where to save extracted SOPs |
| sop_filename_format | `{YYYY-MM-DD}_{slug}_SOP.md` | Required filename pattern — date prefix is non-optional, applied even if `sop_location` is overridden |
| skill_location | .claude/skills/ | Where to save generated skills |

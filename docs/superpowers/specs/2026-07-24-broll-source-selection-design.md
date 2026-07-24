# B-roll source selection + pre-generation timeline — Design

**Date:** 2026-07-24
**Area:** SaaSShorts (AI UGC video generator)
**Files:** `saasshorts.py`, `app.py`, `dashboard/src/components/SaaShortsTab.jsx`, `dashboard/src/lib/i18n.js`

## Problem / Goal

Today every b-roll insert in a SaaSShorts video is an AI-generated still image with a Ken Burns
zoom, driven entirely by the script LLM. The user wants, per b-roll slot, to:

1. Preview and edit the b-roll **prompt** text before generation.
2. Use their **own prepared image** instead of AI generation (same Ken Burns effect).
3. Use their **own video** clip in the slot, inserted **without** the Ken Burns effect.

Plus a **timeline view** on the pre-generation review screen (next to the cost estimate) that
shows, like a video editor, where the talking head is, where the b-roll inserts are, and what type
each insert is (AI / my photo / my video).

### Background: how b-roll works today (for reference)

- Count of inserts = number of script segments with `visual=="broll"` and a truthy `broll_prompt`
  (`saasshorts.py:1447-1451`). The script prompt mandates exactly 2 (segments 2 and 4). It drops to
  1 when the LLM deviates, or when one b-roll generation fails and is silently skipped
  (`saasshorts.py:1489-1490`). **This behavior is unchanged by this work.**
- `generate_broll()` (`saasshorts.py:1010-1076`): fal.ai still image → FFmpeg `zoompan` Ken Burns → 5s clip.
- `composite_video()` (`saasshorts.py:1209-1340`): b-roll is a **cutaway** — it replaces the video
  track for its `[start,end]` window, but the audio for that window still comes from the talking
  head (`[0:a]atrim=...`), so the voiceover continues over the b-roll.
- The whole `script` dict flows from step-2 review to `POST /api/saasshorts/generate`
  (`SaaShortsTab.jsx:346-369`), so new per-segment fields reach the backend for free.

## Decisions (from brainstorming)

- **Granularity:** per-slot. Each b-roll segment picks its own source independently (slot 1 can be
  AI, slot 2 can be my video).
- **Video audio:** per-slot toggle. `broll_mute_audio=true` (default) keeps only the voiceover;
  `false` **mixes** the clip's own audio **together with** the voiceover in that window.
- **Duration:** the slot window (`start`/`end`) is authoritative and manually editable. Video longer
  than the window is trimmed; shorter clamps the window to the video length (current behavior);
  an image is Ken-Burns'd to exactly the window length.
- **Feature 1 scope:** edit the prompt **text** now. Generating an image preview from the prompt
  before final render is **out of scope** (deferred).
- **Timeline:** variant B — a single video track with butt-jointed blocks (head → b-roll → head →
  b-roll → head), colored by type, plus a continuous voiceover track beneath. Each b-roll block is
  clickable and opens the slot editor.

## Data model

Extend b-roll script segments with optional, backward-compatible fields. A segment missing
`broll_source` is treated as `"ai"` — old scripts keep working.

| Field | Type / values | Meaning |
|-------|---------------|---------|
| `broll_source` | `"ai"` (default) \| `"image"` \| `"video"` | slot source |
| `broll_asset_url` | string url | user-uploaded file, when source is image/video (e.g. `/videos/broll_uploads/xxx.png`) |
| `broll_mute_audio` | bool (default `true`) | video only; `true` = voiceover only, `false` = mix clip audio + voiceover |
| `broll_prompt` | string (existing) | edited for AI slots |
| `start` / `end` | number (existing) | slot window, manually editable |

The generate endpoint resolves `broll_asset_url` → a safe local `broll_asset_path` per segment
(mirroring `selected_actor_url` → `selected_actor_path`, `app.py:3575-3597`) before handing the
script to `generate_full_video`.

## Backend

### Upload endpoint — `POST /api/saasshorts/broll-upload`

Mirror `saasshorts_actor_upload` (`app.py:3110-3145`):

- Accept `UploadFile`; require `content_type` startswith `image/` **or** `video/`.
- Size caps: image 25 MB, video 100 MB (bounded read → 413 on overflow).
- Store to `OUTPUT_DIR/broll_uploads/`, filename `broll_{uuid8}.{ext}` (preserve/whitelist ext).
- Gate with `require_managed_entitlement(request)` (cloud mode; no-op self-host).
- Return `{"url": "/videos/broll_uploads/{filename}", "kind": "image"|"video"}`.

### Generation branching — `generate_full_video`, Step 4 (`saasshorts.py:1447-1494`)

For each b-roll segment, branch on `broll_source`:

- `"ai"` (or missing): unchanged — `generate_broll(prompt, ...)`.
- `"image"`: apply **only** the Ken Burns stage to the user's image. Refactor: split
  `generate_broll` into (a) `_ken_burns_clip(img_path, output_path, dur)` holding the existing
  `zoompan` stage (`saasshorts.py:1043-1069`), and (b) the fal image-fetch stage. AI path calls
  fetch → `_ken_burns_clip`; image path calls `_ken_burns_clip` on the uploaded file directly.
- `"video"`: no Ken Burns. Use the uploaded video path directly as the clip; `composite_video`
  already normalizes any input to 1080×1920/30fps.

The runtime clip dict gains audio metadata:
`{"path", "start", "end", "audio_mode": "voiceover"|"mix"}` — `"mix"` only for a `video` slot with
`broll_mute_audio=false`; everything else is `"voiceover"`.

Caching: keep the `{title_slug}_broll_{i}.mp4` convention. For image/video slots, cache is derived
from the uploaded source (copy/normalize into the slot path) so retries reuse it.

### Compositing — `composite_video` b-roll branch (`saasshorts.py:1305-1314`)

- `audio_mode=="voiceover"` (default): unchanged — trim `[0:a]` for the window.
- `audio_mode=="mix"`: build the segment audio as `amix` of the trimmed voiceover `[0:a]` and the
  clip's own audio `[{idx}:a]` (normalize with `dynaudnorm`/`volume` as needed), so both are heard.

Overlap guard: `composite_video` assumes non-overlapping, increasing windows. Since windows are now
user-editable, validate/clamp on the client and defensively sort + skip overlaps server-side.

### Cost estimate (`saasshorts.py:1508-1535`)

Count only `broll_source=="ai"` slots toward the fal/Kling b-roll cost; user-supplied image/video
slots are free.

## Frontend (`SaaShortsTab.jsx`, step 2)

### Timeline component (variant B)

- New component rendering `script.segments` as a single video track of butt-jointed blocks; block
  width ∝ `(end - start)`; color by kind: talking-head (grey), AI (violet), my photo (blue), my
  video (amber). A continuous voiceover track sits beneath. A time ruler (0…`duration_seconds`) on top.
- Placed on the step-2 review screen alongside the cost breakdown.

### Slot editor panel (extends existing `draftScript` editing, `SaaShortsTab.jsx:300-326`)

Clicking a b-roll block opens an inline panel bound to that segment:

- Source radio: **AI** / **Моё фото** / **Моё видео**.
- AI → `textarea` for `broll_prompt`.
- Photo/Video → file input calling `POST /api/saasshorts/broll-upload`; on success store
  `broll_asset_url` + show a thumbnail/preview.
- Video → checkbox “Заглушить звук видео” bound to `broll_mute_audio` (default checked).
- `start` / `end` number inputs for the window, with client-side validation preventing overlap and
  keeping order.

Edits mutate the `script` dict (same pattern as `handleSaveScriptEdit`). No change to the generate
request wiring — the extended script already serializes into the existing POST body.

### i18n

Add Russian/English/Spanish strings for the new labels (source options, mute checkbox, timeline
track labels) in `dashboard/src/lib/i18n.js`.

## Out of scope (v1)

- Adding/removing b-roll slots (count stays LLM-driven; regenerate scripts to change it).
- Generating an image preview from the prompt before final render (deferred).
- Changing the “1 vs 2 inserts” LLM behavior.

## Testing / verification

- Backend: unit-test `broll-upload` (accepts image+video, rejects other types, enforces size caps);
  test the source-branch selection produces the right clip per `broll_source`; test `composite_video`
  emits an `amix` filter only for a `video`+`mix` slot and `[0:a]`-only otherwise (assert on the
  built filter string without invoking FFmpeg).
- Manual: generate one video with slot 1 = AI (edited prompt), slot 2 = my video (mute off) and
  confirm the timeline reflects it, the render cuts to the video, and both voiceover + clip audio
  are audible in that window; a second run with my photo (Ken Burns) and mute-on video.
- `cd dashboard && npm run lint` clean; existing all-AI scripts still render unchanged (regression).

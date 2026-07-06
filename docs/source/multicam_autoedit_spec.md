# Multicam Auto-Edit Platform — Technical Specification & Staged Build Plan

**Self-hosted multicam ingest, transcription, AI content logging, remote review player, and NLE export.**

Target environment: Unraid + Docker. Internet-accessible for remote review. Modular and **stage-gated** so an AI agent can implement and test one piece at a time without holding the whole system in context.

This project is called AUTOEDIT.

---

## 0. How to use this document

**Audience:** AI coding agents and the maintainer.

The work is divided into **modules** (Sections 3–9). Each module is split into **stages**. A stage is sized for a single AI working session: it has a clear goal, the exact inputs it can assume already exist, the outputs it must produce, and a **Definition of Done** with tests that must pass before the stage is considered complete.

**Golden rules for the implementing AI:**

1. **Do not start a stage until its "Depends on" stages are marked done.** Each stage lists its dependencies.
2. **Honour the contracts in Section 2 exactly.** The database schema (2.2) and the Cut Decision List / CDL (2.4) are integration boundaries. Never change them unilaterally — if a change is needed, flag it and stop.
3. **Every stage ends with passing tests.** No stage is "done" because the code exists; it is done when its validation gate passes. Write the tests described in the stage.
4. **Everything an operator might tune is a parameter** (env var or per-project config row), never hardcoded. Defaults are given; all defaults are overridable.
5. **Commit per stage.** One stage ≈ one reviewable change set.

**Performance assumption:** ingest and processing are allowed to be slow (minutes to hours), run once, asynchronously, reviewed later. Only the **review player** has a hard real-time requirement — and now it must perform over the **public internet**, not just LAN (see Section 1.3).

### Lessons from attempt 1 (must not recur)

The previous build failed on three specific things. They are the highest-risk areas; their fixes are called out at the relevant stages and consolidated in Appendix C.

- **Choppy playback** → Module 3 proxy normalisation + Module 7 player engine.
- **Angles never stayed in sync** → Module 3 audio sync + Module 7 drift correction.
- **FCPXML always imported blank into Resolve** → Module 8, which ships with a validation harness.
- (Also) **the LUT never worked** → Module 7 WebGL LUT stage.

---

## 1. System overview

The platform ingests three 1080p H.264 camera angles of a two-person interview, synchronises them on a common timeline using audio, analyses the two speaker audio channels to determine who is talking when, transcribes the dialogue with timestamps, uses a local AI model to log topics and grade conciseness, and produces an automatic multicam cut. The operator reviews the cut **remotely** in a performant in-browser player that can switch angles instantly, overlay a LUT, show topic/speaker metadata on the timeline, and accept timestamped notes from multiple named reviewers. When satisfied, the operator tweaks auto-edit parameters and exports an FCPXML that opens correctly in DaVinci Resolve, optionally regenerated for sub-edits such as "one minute on topic X" or "full edit minus topic Y".

### 1.1 Component map

| #   | Module                     | Responsibility                                                                     | Runtime                |
| --- | -------------------------- | ---------------------------------------------------------------------------------- | ---------------------- |
| 3   | Ingest & normalisation     | Chunked upload, channel mapping, audio sync, playback proxies                      | API + worker           |
| 4   | Audio analysis & VAD       | Loudness floor, per-channel speech detection, speaking intervals                   | Worker (FFmpeg)        |
| 5   | Transcription & AI logging | Whisper transcription w/ timestamps, topic segmentation, conciseness grading       | Worker (Whisper + LLM) |
| 6   | Auto-cut engine            | Turn speaking intervals + rules into a Cut Decision List (CDL)                     | Worker (pure logic)    |
| 7   | Review player              | Frame-accurate multi-angle switching, LUT, metadata timeline, notes — **over WAN** | Browser (frontend)     |
| 8   | Export                     | CDL → FCPXML validated for Resolve                                                 | API                    |
| 9   | Generative features        | Themed sub-edits, YouTube titles, social clips via local LLM                       | Worker (LLM)           |

### 1.2 Containers

All services run on the Unraid host. An implementer may collapse several into one image or split further, but the network contract must hold.

| Container | Image basis                        | Notes                                                                                                         |
| --------- | ---------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `proxy`   | nginx                              | **ALREADY AVAILABLE*** TLS termination, reverse proxy, auth gate. The only container exposed to the internet. |
| `app`     | Node or Python web stack           | REST API + serves the SPA frontend. Sits behind `proxy`.                                                      |
| `worker`  | Same code as `app` + FFmpeg        | Async job queue (ingest, audio, transcribe, cut). Scales to N replicas.                                       |
| `whisper` | whisper.cpp / faster-whisper       | Optional separate container for transcription. Internal only.                                                 |
| `llm`     | Existing local model (Ollama etc.) | **ALREADY RUNNING.** Reached over HTTP. Endpoint is a config value.                                           |
| `db`      | MySQL 8                            | **ALREADY AVAILABLE** if desired, or provision new. Schema in Section 2.                                      |
| `redis`   | redis:7                            | Job queue + transient progress/session state.                                                                 |

> **Integration note.** The local LLM and MySQL already exist in your environment; the spec treats both as external dependencies reached via configurable connection strings. Your Ollama host is 16-core / 32 GB / no GPU, so faster-whisper on CPU with a small model is the realistic transcription baseline.

### 1.3 Access & security (internet-accessible)

Because the player is reachable from the public internet, the following are **mandatory** and are themselves a build module's worth of work (folded into Module 7, Stage 7.0, as a prerequisite gate).

- **TLS everywhere.** Current Peter deployment terminates HTTPS in Nginx Proxy Manager for `ingest.peteflix.uk` and proxies to the host-networked app on `192.168.50.50:8010`. Generic deployments may use another reverse proxy, but this repo's active runbook is NPM, not Caddy. No plaintext HTTP except ACME/health and HTTP→HTTPS redirect.
- **Authentication required for every route except the health check and ACME.** Minimum: a single shared operator password plus per-reviewer display-name; recommended: per-user accounts with bcrypt-hashed passwords in a `users` table and signed, httpOnly session cookies (secret `SESSION_SECRET`). OAuth/SSO is out of scope but the auth layer should not preclude it.
- **Rate limiting & brute-force protection** on the auth and upload endpoints (e.g. fail2ban-style lockout, or proxy-level rate limits).
- **No media served without an authenticated session.** Proxy media (`/data/.../proxy`) and source downloads must be behind auth — use signed, expiring URLs or a streaming endpoint that checks the session; never expose `/data` as a static directory.
- **Range-request streaming.** Proxy video and program audio must be served with HTTP `Range` support so the player can seek over WAN without downloading whole files. This is also load-bearing for player performance (Section 7).
- **Bandwidth realism.** Default proxy is 720p; add a **lower-bitrate "remote" proxy tier** (Stage 3.5b) so reviewers on poor connections can switch quality. The player must tolerate buffering and WAN latency (Section 7.1).
- **CORS / origin checks** locked to `PUBLIC_DOMAIN`.
- **Secrets via env only**, never in the repo. `.env.example` documents every variable.

> **Threat-model note for the implementing AI:** treat all upload content and all reviewer-supplied note text as untrusted. Sanitise note bodies before rendering (XSS), validate file types on upload, and never pass user-supplied paths into shell commands — always resolve and confine paths within `DATA_ROOT`.

---

## 2. Shared architecture & contracts

Everything multiple modules depend on. Implementers of any later module must conform to this section without modifying it.

### 2.1 Storage layout on the Unraid array

Every project is a directory on the main array, bind-mounted into the containers at `/data`. Video, derived audio, transcriptions and the FCPXML all live under the project so a project is fully portable and re-openable. Array root is a parameter (`DATA_ROOT`, default `/mnt/user/automulticam`).

```
/data/<project_id>/
  project.json            # denormalised manifest (mirror of DB, for portability)
  source/
    angleA.mp4            # original uploaded H.264 (re-assembled from chunks)
    angleB.mp4
    angleC.mp4
  proxy/
    angleA.proxy.mp4      # normalised playback proxy, 720p (see 3.5)
    angleB.proxy.mp4
    angleC.proxy.mp4
  proxy_low/              # NEW: low-bitrate remote tier (see 3.5b)
    angleA.proxy.mp4
    ...
  audio/
    ch_presenter.wav      # extracted mono channel, 48k PCM
    ch_interviewee.wav
    program.m4a           # pre-mixed stereo program audio for the player (see 4.6)
    loudness.json         # per-channel RMS envelope @ fixed hop
  transcript/
    transcript.json       # word + segment level, timestamps (see 5.2)
    summary.json          # AI topic log + conciseness grades (see 5.5)
  edit/
    cdl.json              # cut decision list (see 2.4) — the master rough edit
    export.fcpxml         # generated on demand (see 8)
  luts/                   # operator-uploaded .cube LUTs
```

> **Why a proxy dir.** Source footage is immutable. The player **never** plays the source directly — that was a root cause of choppiness. It plays a re-encoded proxy with a forced short keyframe cadence (Stage 3.5) so seeking and angle-switching are cheap. The LUT is applied on top of this flat proxy at view time so it previews correctly.

### 2.2 Database schema (MySQL 8)

Connection fully parameterised: `DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD`. Use a dedicated account with least privilege (SELECT/INSERT/UPDATE/DELETE on the schema; run migrations under a separate privileged account or grant CREATE/ALTER for the migration step only). All timestamps UTC. **All media time offsets stored as `BIGINT` milliseconds** from the synced timeline origin, never floats, to avoid drift.

**`users`** (NEW, for remote auth)

```
id CHAR(26) PK, username VARCHAR(120) UNIQUE, pw_hash VARCHAR(255),
display_name VARCHAR(120), role ENUM('admin','reviewer'), created_at
```

**`projects`**

```
id            CHAR(26) PK         -- ULID
name          VARCHAR(255)
status        ENUM('created','ingesting','processing','ready','error')
fps_num       INT                 -- e.g. 24000  (timeline frame rate numerator)
fps_den       INT                 -- e.g. 1001   (=> 23.976); see 8.3 on rate handling
timeline_origin_ms BIGINT DEFAULT 0
config_json   JSON                -- per-project overrides (thresholds, encoder, etc.)
created_at    DATETIME, updated_at DATETIME
```

**`angles`**

```
id CHAR(26) PK, project_id FK
label VARCHAR(64)                 -- 'presenter','interviewee','wide'
role  ENUM('cam_left','cam_right','wide','other')
source_path VARCHAR(512), proxy_path VARCHAR(512), proxy_low_path VARCHAR(512)
duration_ms BIGINT
sync_offset_ms BIGINT             -- + shifts this angle later on the master timeline
src_fps_num INT, src_fps_den INT
width INT, height INT, vcodec VARCHAR(32)
```

**`audio_channels`**

```
id CHAR(26) PK, project_id FK
speaker_label VARCHAR(64)         -- 'presenter','interviewee'
source_angle_id FK -> angles.id   -- which cam this channel came from
channel_index TINYINT             -- 0=left, 1=right on that source
wav_path VARCHAR(512)
noise_floor_db FLOAT              -- measured (see 4.2)
vad_threshold_db FLOAT            -- effective trigger; operator-overridable
```

**`speaking_intervals`**

```
id BIGINT PK AUTO_INCREMENT, channel_id FK
start_ms BIGINT, end_ms BIGINT    -- on the master timeline
mean_db FLOAT, peak_db FLOAT
INDEX (channel_id, start_ms)
```

**`transcript_segments`**

```
id BIGINT PK AUTO_INCREMENT, project_id FK, channel_id FK
start_ms BIGINT, end_ms BIGINT
text TEXT
words_json JSON                   -- [{w,start_ms,end_ms,conf}] optional word level
INDEX (project_id, start_ms)
```

**`topics`** and **`topic_spans`**

```
topics:      id PK, project_id FK, label VARCHAR(255), colour CHAR(7), description TEXT
topic_spans: id PK, topic_id FK, start_ms, end_ms,
             conciseness_score TINYINT,   -- 1..5 (see 5.4)
             summary TEXT, INDEX(project_id,start_ms)
```

**`cuts`** (one row per edit version) and **`notes`**

```
cuts:  id PK, project_id FK, name VARCHAR(255),
       kind ENUM('rough','themed','social','manual'),
       params_json JSON,          -- the rules used to generate (see 6)
       cdl_json JSON,             -- the CDL itself, also mirrored to edit/cdl.json
       created_at
notes: id PK, project_id FK, cut_id FK NULL, t_ms BIGINT,
       author VARCHAR(120),       -- reviewer display name
       body TEXT, kind ENUM('note','cut_suggestion'),
       created_at, INDEX(project_id,t_ms)
```

**`jobs`**

```
id PK, project_id FK, type VARCHAR(40), state ENUM('queued','running','done','error'),
progress TINYINT, message TEXT, payload_json JSON, error_text TEXT,
created_at, started_at, finished_at
```

### 2.3 Configuration parameters (env)

Defaults shown. All overridable per-deployment via env; threshold-class ones additionally per-project via `projects.config_json`. This source spec includes some aspirational architecture; the current implementation-status truth lives in `AI_HANDOFF.md` and deployment truth lives in `docs/DEPLOYMENT.md`.

| Variable                  | Default                  | Purpose                                  |
| ------------------------- | ------------------------ | ---------------------------------------- |
| `PUBLIC_DOMAIN`           | (required)               | FQDN for TLS + CORS                      |
| `SESSION_SECRET`          | (required)               | Signs session cookies                    |
| `DATA_ROOT`               | `/mnt/user/automulticam` | Array path for projects                  |
| `DB_*`                    | (required)               | MySQL connection                         |
| `REDIS_URL`               | `redis://redis:6379`     | Queue + sessions                         |
| `OLLAMA_BASE_URL`         | `http://llm:11434`       | Local Ollama model endpoint              |
| `LLM_MODEL`               | `qwen2.5:14b`            | Model for logging/generation             |
| `WHISPER_BACKEND`         | `faster-whisper`         | or whisper.cpp / external                |
| `WHISPER_MODEL`           | `small.en`               | CPU-realistic on no-GPU host             |
| `PROXY_ENCODER`           | `h264_vaapi`             | Intel VAAPI hardware path; `libx264` software fallback; `h264_qsv` only after QSV is fixed |
| `PROXY_GOP`               | `12`                     | Keyframe interval (frames) for seek perf |
| `PROXY_HEIGHT`            | `720`                    | Main proxy height                        |
| `PROXY_LOW_HEIGHT`        | `360`                    | Remote/low-bandwidth proxy height        |
| `UPLOAD_MAX_CHUNK_BYTES`  | `67108864`               | Max resumable-upload chunk size in bytes |
| `VAD_DEFAULT_HANGOVER_MS` | `300`                    | Speech off-debounce                      |
| `CUT_MIN_SHOT_MS`         | `250`                    | Direct-cut micro-guard; raise only to loosen twitchy edits |

### 2.4 Cut Decision List (CDL) — the master contract

The CDL is the single artifact the auto-cut engine produces (Module 6), the player consumes (Module 7), and the exporter translates (Module 8). Plain JSON, frame-aligned to the project frame rate. **If a module touches the edit, it touches the CDL and nothing else.**

```json
{
  "version": 1,
  "project_id": "01J...",
  "fps": { "num": 24000, "den": 1001 },
  "audio": { "channels": ["ch_presenter_id", "ch_interviewee_id"] },
  "clips": [
    {
      "angle_id": "01J...",
      "src_in_ms": 12000,
      "timeline_in_ms": 0,
      "dur_ms": 3400,
      "reason": "speaker:interviewee"
    }
  ],
  "luts": { "active": "luts/mylook.cube" }
}
```

**Invariants the exporter relies on:** clips sorted by `timeline_in_ms`; each clip's `timeline_in_ms` equals the previous clip's end (contiguous, no gaps/overlaps); every `src_in_ms` and `dur_ms` is an exact frame multiple; every `angle_id` resolves to a row in `angles`. Module 8 contains a validator that rejects a CDL violating any invariant before attempting export.

### 2.5 Job lifecycle

Long-running work is currently executed in-process/background-thread style in the app. The queued worker lifecycle below is an architectural target for a future Redis/worker stage, not the current implementation. When that stage lands, the API should return a job id immediately; the frontend polls `GET /jobs/:id` or subscribes via SSE. Every job updates `progress` and a human-readable `message`. Jobs are idempotent and resumable where possible (re-running transcription overwrites `transcript.json` atomically).

1. **created → ingesting:** chunks assembled, ffprobe metadata captured.
2. **ingesting → processing:** sync, proxy encode, loudness, VAD, transcription, AI logging, initial rough cut — each a sub-job with its own progress.
3. **processing → ready:** CDL written; project openable in the player.
4. **error:** any sub-job failure sets `project.status=error` with `error_text`; sub-jobs are individually retryable.

---

## Stage conventions

Each stage below uses this template:

- **Goal** — one sentence.
- **Depends on** — stages that must be done first.
- **Inputs you may assume exist** — what's already built/available.
- **Build** — what to implement.
- **Definition of Done** — the validation gate. All checks must pass.

A suggested whole-project order is in Appendix A. Within a module, stages are strictly ordered unless noted.

---

## 3. Module: Ingest & normalisation

**Module goal:** accept three video files reliably over the internet despite timeouts, map audio channels to speakers, compute a per-angle audio sync offset, and produce normalised playback proxies (two bitrate tiers). Outputs: populated `angles` + `audio_channels` rows and proxy files.

### Stage 3.1 — Project + DB bootstrap

- **Goal:** create a project and the schema it lives in.
- **Depends on:** none (this is the first code stage of the whole build).
- **Inputs you may assume exist:** MySQL reachable via `DB_*`.
- **Build:** migrations for all tables in 2.2; `POST /projects` (name, fps_num, fps_den) → creates row + `/data/<id>/` skeleton dirs + `project.json`. `GET /projects/:id` returns the manifest.
- **Definition of Done:**
  - Migrations run clean on an empty DB and are idempotent (re-run = no-op).
  - Creating a project returns a ULID and creates the directory tree on `DATA_ROOT`.
  - Unit test: invalid fps (0 or non-integer) is rejected with 400.
  - `project.json` on disk matches the DB row.

### Stage 3.2 — Chunked resumable upload

- **Goal:** get three large files onto the array without timeout failures.
- **Depends on:** 3.1.
- **Inputs:** a created project.
- **Build:** client splits each file into chunks no larger than `UPLOAD_MAX_CHUNK_BYTES`; `POST /upload/:uploadId/chunk/:index` appends to a temp file; `GET /upload/:uploadId` returns highest contiguous chunk received (resume); `POST /upload/:uploadId/complete` validates byte count + client SHA-256, then moves the assembled file to `source/` and creates the `angles` row (no proxy yet).
- **Definition of Done:**
  - **Resilience test:** kill the connection mid-upload; resume; final file SHA matches original.
  - Concurrent upload of 3 files to one project works.
  - A wrong SHA on `complete` is rejected and the temp file is cleaned up.
  - Path-traversal attempt in `uploadId`/filename is rejected (confined to `DATA_ROOT`).

### Stage 3.3 — Probe & channel mapping

- **Goal:** capture media metadata and let the operator declare which audio channel is which speaker.
- **Depends on:** 3.2.
- **Build:** run `ffprobe -show_streams -show_format -of json` per source; fill `angles` (w/h/fps/codec/duration). Soft-warn (allow override) if not 1080p H.264. `POST /projects/:id/channels` accepts the operator's mapping: for each source/channel pair, a speaker label + role, plus an optional **manual sync nudge** (±ms) per angle. Only the two speaker channels are kept; all other audio ignored.
- **Definition of Done:**
  - `angles` rows have correct fps/codec/dimensions for the test clips.
  - Mapping creates the two `audio_channels` rows with correct `source_angle_id`/`channel_index`.
  - Non-1080p input produces a warning but still proceeds when forced.

### Stage 3.4 — Channel extraction + audio sync

- **Goal:** extract speaker channels and compute per-angle sync offsets from audio.

- **Depends on:** 3.3.

- **Build:**
  
  - Extract each mapped channel to mono 48 k PCM WAV:
    
    ```
    ffmpeg -i source/angleA.mp4 -map_channel 0.1.0 -ac 1 -ar 48000 -c:a pcm_s16le audio/ch_presenter.wav
    ffmpeg -i source/angleA.mp4 -map_channel 0.1.1 -ac 1 -ar 48000 -c:a pcm_s16le audio/ch_interviewee.wav
    ```
  
  - Sync: extract a mono guide track per angle (full mix), band-pass 300–3000 Hz, downsample to 8 k, FFT cross-correlate each angle against a reference over a bounded lag window (±10 s); peak lag = `sync_offset_ms`. Reference offset = 0; set `timeline_origin_ms` so all offsets ≥ 0. Apply any operator nudge from 3.3.

- **Definition of Done:**
  
  - Two WAVs exist; correct speaker audible in each (manual spot check + RMS sanity).
  - **Sync test (the attempt-1 failure):** a known clapper/transient aligns within **±1 frame** across all three angles after offsets are applied.
  - Offsets are stored as integer ms; reference angle is exactly 0.

> **Why this matters:** sync was derived from container timestamps before (they lie) and never held. Deriving it from audio + storing integer ms + applying identically in player and exporter is the fix.

### Stage 3.5 — Proxy normalisation (main tier)

- **Goal:** produce smooth-seeking 720p proxies — the primary fix for choppy playback.

- **Depends on:** 3.3 (needs source + probe).

- **Build:**
  
  ```
  ffmpeg -i source/angleA.mp4 \
    -vf scale=-2:${PROXY_HEIGHT} \
    -c:v ${PROXY_ENCODER} -profile:v high -pix_fmt yuv420p \
    -g ${PROXY_GOP} -keyint_min ${PROXY_GOP} -sc_threshold 0 \
    -preset veryfast -crf 20 \
    -movflags +faststart \
    -an \
    proxy/angleA.proxy.mp4
  ```
  
  Proxies are **silent** (audio served separately, see 4.6) and **flat** (no LUT baked in). Identical `-g` across angles means aligned keyframes so switches snap cleanly. Store `proxy_path`.

- **Definition of Done:**
  
  - Proxy opens in Chrome `<video>`.
  - **Seek test:** seek to a random point completes in **< 100 ms** locally.
  - Every angle has a keyframe at the same cadence (verify with `ffprobe -show_frames | grep key_frame`).

### Stage 3.5b — Low-bitrate remote proxy tier (NEW)

- **Goal:** a smaller proxy for reviewers on poor WAN connections.
- **Depends on:** 3.5.
- **Build:** same command at `PROXY_LOW_HEIGHT` (default 360p) and a lower bitrate target (e.g. `-crf 26` or `-b:v 800k`), written to `proxy_low/`; store `proxy_low_path`. The player (7.x) offers a quality toggle defaulting to auto based on measured throughput.
- **Definition of Done:**
  - Low proxy is materially smaller (≥ 3× smaller file than main tier on the test clip).
  - Both tiers are frame-aligned with each other (same `-g`, same duration in frames).

### Stage 3.6 — Range-request media streaming (NEW, required for remote)

- **Goal:** serve proxies and program audio over HTTPS with seek support, behind auth.
- **Depends on:** 3.5, and Stage 7.0 auth gate (may be built in parallel but must be wired before public exposure).
- **Build:** an authenticated streaming endpoint that honours HTTP `Range` for `proxy`, `proxy_low`, and `audio/program.m4a`. Never expose `/data` as static. Optionally issue short-lived signed URLs.
- **Definition of Done:**
  - `curl -H "Range: bytes=1000000-1100000"` returns `206 Partial Content` with correct length.
  - Unauthenticated request returns `401`/redirect, never media bytes.
  - Player can seek a 2 GB proxy over a throttled connection without downloading the whole file.

### Module 3 acceptance (all stages)

| Check            | Pass criteria                                |
| ---------------- | -------------------------------------------- |
| Resumable upload | Interrupted upload resumes; SHA matches      |
| Probe            | `angles` rows correct                        |
| Channel extract  | Two WAVs, correct speaker each               |
| Sync             | Clapper aligns within ±1 frame across angles |
| Proxy seek       | Random seek < 100 ms; keyframes aligned      |
| Remote stream    | 206 on Range; media gated by auth            |

---

## 4. Module: Audio analysis & speech detection

**Module goal:** for each speaker channel, measure a noise floor and produce speaking intervals on the master timeline; also produce the pre-mixed program audio the player uses. Outputs: `speaking_intervals` rows, `audio/loudness.json`, `audio/program.m4a`.

### Stage 4.1 — Loudness envelope

- **Goal:** a cheap per-channel energy envelope for detection and for the player's waveform lane.

- **Depends on:** 3.4 (needs extracted WAVs + offsets).

- **Build:** short-window RMS-dB per channel at a fixed hop (default 20 ms) → `loudness.json`:
  
  ```json
  { "hop_ms": 20,
    "channels": {
      "ch_presenter_id":   { "rms_db": [-52,-50, "..."], "start_ms": 0 },
      "ch_interviewee_id": { "rms_db": ["..."], "start_ms": 0 } } }
  ```

- **Definition of Done:** array length ≈ duration/hop; values plausible; file re-readable by the player without touching the WAV.

### Stage 4.2 — Noise floor & threshold

- **Goal:** an explainable speech trigger the operator can raise.
- **Depends on:** 4.1.
- **Build:** floor = low percentile (10th) of the RMS-dB distribution per channel → `noise_floor_db`. Effective trigger = floor + margin (default +8 dB) → `vad_threshold_db`, **operator-overridable per channel** (the "raise the trigger" control). Optionally combine with a real VAD (Silero/WebRTC) for robustness, but the energy gate is the required default.
- **Definition of Done:** quiet-room floor within a few dB of a manual measure; raising `vad_threshold_db` monotonically reduces detected speech.

### Stage 4.3 — Interval construction

- **Goal:** turn the envelope into clean speaking intervals.
- **Depends on:** 4.2.
- **Build:** mark frames above threshold as speech; merge gaps shorter than `VAD_DEFAULT_HANGOVER_MS` (debounce); drop bursts shorter than 150 ms (lip smacks/coughs); write to `speaking_intervals` with mean/peak dB.
- **Definition of Done:**
  - A 200 ms pause inside a sentence does **not** split the interval at 300 ms hangover.
  - On a labelled test WAV, detected intervals match ground truth within the hangover tolerance.

### Stage 4.4 — Derived activity timeline

- **Goal:** the structure the cut engine consumes (who is active when, including overlap).

- **Depends on:** 4.3.

- **Build:** because speakers are on separate channels, overlap = both channels active. Emit (in-memory or persisted) a contiguous activity timeline:
  
  ```json
  [ { "start_ms":0, "end_ms":4000, "active":["presenter"] },
    { "start_ms":4000, "end_ms":4600, "active":["presenter","interviewee"] },
    { "start_ms":4600, "end_ms":5200, "active":[] } ]
  ```

- **Definition of Done:** simultaneous speech produces an overlap region; timeline is contiguous and covers the whole duration.

### Stage 4.6 — Program audio mixdown (NEW, for the player)

- **Goal:** one stereo audio file the player uses as its master clock.
- **Depends on:** 3.4.
- **Build:** mix the two speaker channels to a single stereo `audio/program.m4a` (AAC, faststart). This is what the player plays; video follows it. Keep it sample-accurate against the master timeline (i.e. account for offsets so audio t=0 is timeline origin).
- **Definition of Done:** `program.m4a` plays in browser; its t=0 corresponds to timeline origin; both speakers audible.

### Module 4 acceptance

| Check              | Pass criteria                                 |
| ------------------ | --------------------------------------------- |
| Floor              | Within a few dB of manual measure             |
| Threshold override | Raising it reduces intervals monotonically    |
| Hangover           | 200 ms internal pause doesn't split at 300 ms |
| Overlap            | Simultaneous speech → overlap region          |
| Program audio      | Plays; aligned to timeline origin             |

---

## 5. Module: Transcription & AI content logging

**Module goal:** transcribe each speaker channel with timestamps, then use the local LLM to segment into topics, summarise, and grade conciseness. Outputs: `transcript_segments`, `topics`, `topic_spans`, `transcript/*.json`.

### Stage 5.1 — Transcription

- **Goal:** word/segment timestamps per speaker on the master timeline.

- **Depends on:** 3.4 (WAVs + offsets).

- **Build:** transcribe each speaker channel separately (cleaner attribution than diarising a mix) via `WHISPER_BACKEND` (default faster-whisper `small.en`, CPU). Convert Whisper times to master-timeline ms by adding the channel's source angle `sync_offset_ms`. Write `transcript.json`:
  
  ```json
  { "segments": [
     { "channel_id":"...", "speaker":"presenter",
       "start_ms":12000, "end_ms":15200, "text":"so tell me about...",
       "words":[{"w":"so","start_ms":12000,"end_ms":12120,"conf":0.98}] } ] }
  ```
  
  Also persist to `transcript_segments`.

- **Definition of Done:**
  
  - **Offset check:** spot-check 3 words — word time + sync offset = correct master time.
  - Long file processes without OOM on the no-GPU host (chunk internally if needed).

### Stage 5.2 — Topic segmentation (LLM)

- **Goal:** segment dialogue into non-overlapping topic spans.

- **Depends on:** 5.1.

- **Build:** feed merged, speaker-tagged, timestamped transcript to the LLM in windows (~3–4k tokens with overlap, respecting model context length), then stitch. Force JSON-only output; parse defensively with retry on malformed output. System prompt template (config):
  
  ```
  You segment interview transcripts into coherent topics.
  Return ONLY JSON: [{label, start_ms, end_ms, summary, conciseness}].
  conciseness is 1-5: 5 = tight and on-point, 1 = rambling/repetitive.
  Use the provided timestamps; spans must not overlap and should be contiguous.
  ```
  
  Persist `topics` + `topic_spans`.

- **Definition of Done:**
  
  - Spans cover > 95% of dialogue with **no overlaps**.
  - Malformed LLM output is caught and retried; the job never crashes.

### Stage 5.3 — Conciseness grading

- **Goal:** a defensible 1–5 score per span, not pure model opinion.
- **Depends on:** 5.2.
- **Build:** keep the LLM score, and add a deterministic signal (words-per-point ratio, filler-word density, answer duration vs. median). Store both — LLM score in `conciseness_score`, rationale + deterministic metrics in `summary`.
- **Definition of Done:** every span has `conciseness ∈ 1..5`; deterministic metrics present and reproducible.

### Stage 5.5 — Report output

- **Goal:** the single file the reporting UI and timeline lane read.

- **Depends on:** 5.3, 4.4.

- **Build:** `summary.json` combining topics, per-topic speaker time, grades, and totals:
  
  ```json
  { "topics":[ {"label":"childhood","colour":"#C0392B",
       "spans":[{"start_ms":0,"end_ms":1,"conciseness":4,"summary":"..."}],
       "speaker_time_ms":{"presenter":4200,"interviewee":38000} } ],
    "totals":{"speaker_time_ms":{"presenter":0,"interviewee":0},
              "talk_overlap_ms":0,"silence_ms":0} }
  ```

- **Definition of Done:** numbers reconcile with `speaking_intervals` (speaker totals match within rounding); file loads in the player's timeline lane.

### Module 5 acceptance

| Check            | Pass criteria                              |
| ---------------- | ------------------------------------------ |
| Timestamp offset | word time + offset = master time           |
| JSON robustness  | malformed LLM output never crashes job     |
| Coverage         | topic spans > 95%, no overlaps             |
| Grades           | 1..5 for every span + deterministic signal |

---

## 6. Module: Auto-cut engine

**Module goal:** pure, deterministic logic that turns the activity timeline + rules into a valid CDL (2.4). No media touched. Fully unit-testable with synthetic interval data.

### Stage 6.1 — Core cut algorithm

- **Goal:** rough-cut CDL from the activity timeline.

- **Depends on:** 4.4 (activity timeline), 2.4 (CDL contract). Can be developed against **synthetic** activity data before Module 4 exists.

- **Build:** walk the activity timeline:
  
  - single speaker active → that speaker's cam;
  - both active and `overlap_to_wide` → wide;
  - neither active → wide by default (`silence_behaviour='wide'`), or optionally hold last angle.
    The baseline method is **direct**: use the raw activity edges as the cut edges, with no intentional lead/tail delay. `lead_in_ms`, `tail_ms`, and higher `min_shot_ms` values are loosening controls only. Resolve each shot to a clip: `angle_id`, `src_in_ms = timeline_in_ms − angle.sync_offset_ms`, `dur_ms`. **Snap every boundary to a whole frame** for the project fps before writing.

- **Rule parameters** (stored in `cuts.params_json`):
  
  | Param                  | Default | Effect                                              |
  | ---------------------- | ------- | --------------------------------------------------- |
  | `min_shot_ms`          | 250     | Tiny direct-cut guard against detector chatter; raise to loosen |
  | `overlap_to_wide`      | true    | Both speaking → cut to wide                         |
  | `wide_interval_ms`     | 0       | If >0, relief wide after long solo stretches around this cadence |
  | `wide_interval_jitter` | 0.3     | Randomness factor for the above                     |
  | `lead_in_ms`           | 0       | Optional pre-roll before a speaker starts; keep 0 for direct cuts |
  | `tail_ms`              | 0       | Optional hold after a speaker stops; keep 0 for direct cuts |
  | `silence_behaviour`    | wide    | 'wide' or 'hold' when nobody is speaking            |

  **Default editorial profile: Direct.** AUTOEDIT should start by cutting immediately to the active single speaker, cutting to wide during overlap, and cutting to wide in silence. If the result feels too twitchy, loosen it deliberately: raise `min_shot_ms` to ~600–1200 ms, add `tail_ms` around 100–250 ms, optionally add `lead_in_ms` around 80–120 ms, or enable `wide_interval_ms` (for example 45–90 s) as a relief-wide when one person has been on screen too long.

  **Existing-project rule:** `cuts.params_json` is stored per generated cut. Changing defaults or deploying new code does not rewrite old cuts. To make an existing project use Direct behavior, regenerate the rough cut from the player Direct preset or call `POST /projects/{id}/cut` with the Direct params above.

- **Definition of Done:**
  
  - **Determinism:** same intervals + params → byte-identical CDL.
  - **Anti-jitter:** no clip shorter than `min_shot_ms`.
  - **Overlap:** simultaneous-speech regions resolve to the wide angle.
  - **Frame snapping (attempt-1 fix):** every `src_in_ms`/`dur_ms` is an exact frame multiple.

### Stage 6.2 — Anti-jitter & periodic wide

- **Goal:** polish the cut feel.
- **Depends on:** 6.1.
- **Build:** enforce `min_shot_ms` by merging/extending short shots into neighbours (prefer extending the incoming speaker). Direct mode keeps this value low; looser profiles raise it. Inject jittered relief wides if `wide_interval_ms > 0`, but only where they don't violate `min_shot_ms`.
- **Definition of Done:** with a pathological rapid-fire back-and-forth input, output respects `min_shot_ms`; periodic wides appear at roughly the requested cadence.

### Stage 6.3 — Sub-edit generation (themed / social)

- **Goal:** shorter edits selected by topic.
- **Depends on:** 6.1, 5.5 (topics).
- **Build:** select time ranges first, then run the cut algorithm over only those ranges re-based onto a new contiguous timeline. Each sub-edit is a new `cuts` row with `kind` set and selection params recorded (reproducible).
  - "10 minutes on themes X, Y, Z" → gather matching `topic_spans`, rank by conciseness + duration, fill to target length, order chronologically, cut.
  - "Full edit minus theme Y" → include everything except spans labelled Y.
  - "1 minute on topic X (most interesting bit)" → ask the LLM to rank candidate spans of X for punchiness; take the best contiguous ~60 s window.
- **Definition of Done:**
  - "minus theme Y" CDL contains **zero** Y-labelled time.
  - Themed edit duration is within a tolerance of the requested length.
  - Each sub-edit re-opens correctly in the player and passes the 8.2 validator.

### Module 6 acceptance

| Check       | Pass criteria                                     |
| ----------- | ------------------------------------------------- |
| Determinism | identical output for identical input              |
| Anti-jitter | no sub-`min_shot_ms` clips                        |
| Overlap     | wide on simultaneous speech                       |
| Contiguity  | clips contiguous, frame-aligned, validator passes |
| Themed      | "minus theme Y" excludes all Y time               |

---

## 7. Module: Review player (remote-capable)

**Module goal:** a performant browser player — usable **over the public internet** — that plays the auto-cut, switches any of the three angles without skipping, keeps program audio constant, applies a LUT over the flat proxy, shows a colour-coded metadata timeline, supports skip-to-topic, manual overrides, and multi-author timestamped notes. This is the only hard real-time component and owns two of the three attempt-1 failures.

### Stage 7.0 — Auth gate + reverse proxy (NEW, prerequisite for any public exposure)

- **Goal:** nobody reaches the app or media without TLS + a session.
- **Depends on:** 3.1.
- **Build:** Nginx Proxy Manager terminates HTTPS for `PUBLIC_DOMAIN` in the current Unraid deployment and reverse-proxies to the host-networked app on port 8010. Other deployments may use Caddy/nginx, but Peter's canonical path is NPM. Login endpoint (shared password minimum, or `users` table with bcrypt + signed httpOnly cookies). Rate-limit auth + upload. CORS locked to `PUBLIC_DOMAIN`.
- **Definition of Done:**
  - All routes except health + ACME require a session.
  - TLS cert provisions; plain HTTP redirects.
  - Brute-force lockout triggers after N failed logins.
  - Reviewer can set a display name that is attached to their notes.

### Stage 7.1 — Player engine (the smoothness/sync fix)

- **Goal:** frame-accurate angle switching with no stutter and locked sync, tolerant of WAN.
- **Depends on:** 3.5/3.5b/3.6 (proxies + range streaming), 4.6 (program audio), 6.1 (a CDL to play).
- **Build:**
  1. **One `<audio>` element is the master clock** — plays `program.m4a`. All video follows `audio.currentTime`.
  2. **Two `<video>` elements, ping-pong:** one visible, one hidden pre-seeking the next clip's angle/time. At a cut boundary, swap visibility/roles. Pre-rolling the next clip kills switch stutter.
  3. **Manual override:** load the chosen angle into the hidden element at current master time, wait for `seeked`, swap. Persists until "back to auto".
  4. **Drift correction:** each animation frame, if `abs(video.currentTime − audio.currentTime) > 1 frame`, nudge the video — guarantees angles stay locked to the same moment.
  5. **WAN tolerance:** buffer-aware — if the next clip's segment isn't buffered, hold current angle a beat rather than showing a stall; expose a quality toggle (main/low proxy) and default by measured throughput.
- **Definition of Done:**
  - Plays the full rough cut with **no visible stutter** at switches.
  - Manual switch reflects within ~1–2 frames, **no audio glitch** (audio never reloads on a video switch).
  - **Sync lock (attempt-1 fix):** forced angle shows the same moment as audio (clapper test) within **1 frame**.
  - Seek anywhere → correct angle+time playing in **< 200 ms** locally; degrades gracefully over a throttled connection.
  - **Fallback documented:** if `<video>` ping-pong still stutters on target hardware, implement WebCodecs decode-to-canvas (demux proxy, decode only needed frames, one decoder). Build the `<video>` path first and measure before reaching for this.

### Stage 7.2 — Metadata timeline & navigation

- **Goal:** see and jump around the content.
- **Depends on:** 7.1, 5.5 (summary), 6.1 (CDL).
- **Build:** scrubber with stacked lanes — (1) angle/speaker colour blocks from CDL, (2) topic colour blocks from `summary.json`, (3) optional energy waveform from `loudness.json`, (4) note markers. Click a topic/note to seek. Current angle label over the video; A/B/C manual control + "back to auto".
- **Definition of Done:** clicking a topic seeks there; lanes render from the JSON without re-reading media; current-angle label tracks the CDL.

### Stage 7.3 — LUT application (attempt-1 fix)

- **Goal:** preview the graded look over the flat proxy.
- **Depends on:** 7.1.
- **Build:** parse `.cube` LUTs into a 3D texture; apply in a WebGL shader over the visible video frame (do **not** bake into the proxy). LUT selectable per project from `/data/<project>/luts/`; upload via `POST /projects/:id/luts`.
- **Definition of Done:** toggling the LUT visibly changes the grade with **no frame drop**; a known `.cube` produces the expected look; must be demoed working on day one of this stage.

### Stage 7.4 — Notes (multi-author)

- **Goal:** timestamped review notes from named reviewers.
- **Depends on:** 7.0 (display name), 7.2 (timeline).
- **Build:** add note at current playhead → `POST /projects/:id/notes` with `t_ms, author, body, kind`. Render as markers; `kind='cut_suggestion'` (e.g. "cut this point") renders distinctly so it can be actioned when tweaking the edit. **Sanitise `body` on render (XSS).**
- **Definition of Done:** two different reviewers' notes appear with correct authors and times; clicking a marker seeks there; injected `<script>` in a note body does not execute.

### Module 7 acceptance

| Check         | Pass criteria                                |
| ------------- | -------------------------------------------- |
| Auth          | no media/app access without session over TLS |
| Auto playback | no stutter at switches                       |
| Manual switch | ~1–2 frames, no audio glitch                 |
| Sync lock     | forced angle matches audio within 1 frame    |
| Seek          | correct angle+time < 200 ms local            |
| LUT           | visible grade change, no frame drop          |
| Notes         | multi-author, seekable, XSS-safe             |

---

## 8. Module: NLE export (FCPXML for Resolve)

**Module goal:** translate a CDL into an FCPXML that opens in DaVinci Resolve as a multi-clip timeline referencing the **original** source media, with cuts at the CDL boundaries. Declared essential; was always blank before, so this module ships with a validation harness.

> **Essential & previously broken.** Attempt 1's FCPXML imported blank. Common causes: (a) referencing files Resolve can't resolve on disk, (b) wrong/old FCPXML version, (c) frame-rate format mismatch between project and assets, (d) missing format/asset declarations. Each is addressed below. **Not done until a generated file produces a populated timeline in your Resolve.**

### Stage 8.1 — CDL validator

- **Goal:** never emit a broken file.
- **Depends on:** 2.4, 6.1.
- **Build:** validate before every export — clips sorted, contiguous, non-overlapping; each `timeline_in_ms` == previous end; every `dur_ms`/`src_in_ms` an exact frame multiple for project fps; every `angle_id` resolves; every referenced source exists on disk with probed duration covering `src_in_ms + dur_ms`. Fail loudly with the offending clip index.
- **Definition of Done:** a deliberately broken CDL (sub-frame value, gap, missing file) is rejected with a precise error; a valid CDL passes.

### Stage 8.2 — FCPXML writer

- **Goal:** the actual file.

- **Depends on:** 8.1.

- **Build:** target a Resolve-supported FCPXML version (e.g. 1.9; make it a parameter). Reference original media in `source/`. Frame rate as a rational (`num/den`) so 23.976 = 24000/1001 is exact; express times as rational seconds (`"1001/24000s"`); the format's `frameDuration` **must** match the asset rate. Skeleton:
  
  ```xml
  <fcpxml version="1.9">
    <resources>
      <format id="r1" frameDuration="1001/24000s" width="1920" height="1080"/>
      <asset id="a1" start="0s" duration="...s" hasVideo="1" hasAudio="1"
             format="r1" src="file:///data/proj/source/angleA.mp4"/>
      <!-- one asset per angle -->
    </resources>
    <library><event><project><sequence format="r1">
      <spine>
        <asset-clip ref="a1" offset="0s" start="500500/24000s" duration="81081/24000s"/>
        <!-- one per CDL clip -->
      </spine>
    </sequence></project></event></library>
  </fcpxml>
  ```
  
  `offset` = position on the timeline; `start` = in-point into the asset (= CDL `src_in_ms` as rational); `duration` = CDL `dur_ms` as rational. All three exact frame multiples.

- **Definition of Done:**
  
  - **Opens populated in Resolve** (not blank) — the gate.
  - Cuts land on the same frames as the player preview.
  - Resolve finds or relinks the three source files.
  - No "conform" warning / no audio drift across the timeline.

### Stage 8.3 — OTIO fallback (optional, recommended)

- **Goal:** de-risk the format.
- **Depends on:** 8.1.
- **Build:** CDL → OpenTimelineIO, then let OTIO adapters emit FCPXML/EDL/AAF. If hand-written FCPXML proves fragile in your Resolve build, switch the default exporter to this path.
- **Definition of Done:** OTIO-generated FCPXML also opens populated in Resolve; EDL export available as a secondary option.

### Module 8 acceptance

| Check             | Pass criteria                       |
| ----------------- | ----------------------------------- |
| Validator         | broken CDL rejected with clip index |
| Imports populated | timeline has clips in Resolve       |
| Cuts correct      | frames match player preview         |
| Relink            | source files found/relinkable       |
| Rate              | no conform warning, no drift        |

---

## 9. Module: Generative AI features

**Module goal:** operator conveniences on the local LLM. All optional, additive, off the critical path.

### Stage 9.1 — Natural-language sub-edit requests

- **Depends on:** 6.3.
- **Build:** UI where the operator types a request ("1 minute on the immigration topic", "full edit minus small talk"); LLM parses intent → selection params (topic labels + target length); run 6.3; create a `cuts` row; offer in player + exporter.
- **Definition of Done:** three example phrasings each produce a sensible, playable sub-edit.

### Stage 9.2 — YouTube title generator

- **Depends on:** 5.5.
- **Build:** from topics + summaries, prompt the LLM for N titles across labelled strategies (curiosity gap, controversy, named-guest, listicle, plainspoken); return JSON grouped by strategy; let the operator regenerate per strategy and copy individual titles. Store nothing unless saved.
- **Definition of Done:** titles return grouped by strategy; regeneration works; output is valid JSON every time (defensive parse).

### Stage 9.3 — Implementation notes

- All prompts are config templates (tunable without code changes).
- Respect model context length; chunk transcript inputs.
- Cache LLM responses keyed by input hash to avoid recompute on the no-GPU host.

---

## Appendix A — Recommended global build order

Each item is a stage gate; do not proceed until the prior gate's Definition of Done passes.

1. **3.1** Project + DB bootstrap
2. **7.0** Auth gate + reverse proxy *(early, so nothing is ever exposed unauthenticated)*
3. **3.2** Chunked upload
4. **3.3** Probe + channel mapping
5. **3.4** Channel extraction + sync
6. **3.5 / 3.5b** Proxies (both tiers)
7. **3.6** Range streaming
8. **4.1 → 4.4, 4.6** Audio analysis + program mixdown
9. **6.1** Core cut engine *(can begin earlier against synthetic data)*
10. **6.2** Anti-jitter / periodic wide
11. **5.1 → 5.5** Transcription + AI logging
12. **7.1** Player engine
13. **7.2 → 7.4** Timeline, LUT, notes
14. **8.1 → 8.2** Validator + FCPXML *(highest external risk; test against real Resolve early)*
15. **6.3** Sub-edits
16. **9.x** Generative features
17. **8.3** OTIO fallback if FCPXML proves fragile

Parallelisable: 6.1 vs Module 4/5; 7.x vs 8.x once 6.1 exists.

## Appendix B — API surface (indicative)

```
POST   /auth/login                       start session
POST   /projects                         create
POST   /upload/:uploadId/chunk/:index    upload chunk
GET    /upload/:uploadId                 resume info
POST   /upload/:uploadId/complete        finalise -> queue ingest
POST   /projects/:id/channels            channel map + manual sync nudge
POST   /projects/:id/process             kick processing pipeline
GET    /jobs/:id        (or SSE /jobs/:id/stream)   job progress
GET    /projects/:id                     manifest + status
GET    /projects/:id/cdl/:cutId          fetch a CDL for the player
POST   /projects/:id/cuts                generate cut (params or NL request)
POST   /projects/:id/notes               add note
GET    /media/:projectId/:kind/:angle    auth + Range-aware stream (proxy/proxy_low/program)
POST   /projects/:id/export/:cutId       -> FCPXML (download)
POST   /projects/:id/luts                upload .cube
```

## Appendix C — Risk register (attempt-1 failures)

| Risk                       | Stage(s) that mitigate | Mechanism                                                                  |
| -------------------------- | ---------------------- | -------------------------------------------------------------------------- |
| Choppy playback            | 3.5, 7.1               | Short-GOP proxies + ping-pong video + shared audio clock                   |
| Angles out of sync         | 3.4, 7.1               | Audio cross-correlation offsets in integer ms + per-frame drift correction |
| Blank FCPXML in Resolve    | 8.1–8.2                | Validator + exact rational frame rates + tested skeleton + OTIO fallback   |
| LUT never worked           | 7.3                    | WebGL `.cube` 3D-texture shader over flat proxy                            |
| Public exposure risk (NEW) | 1.3, 7.0, 3.6          | TLS, auth on every route, gated Range streaming, input sanitisation        |

## Appendix D — Testing strategy (cross-cutting)

- **Unit tests** are mandatory for pure logic: the cut engine (6.x) and the CDL validator (8.1) must have full unit coverage with synthetic inputs — no media required.
- **Golden-file tests:** keep a tiny 30 s three-angle test set (with a clapper near the start) in the repo's test fixtures. Sync (3.4), proxy (3.5), transcription offset (5.1), and FCPXML (8.2) all assert against it.
- **Contract tests:** a CDL fixture that the player loads and the exporter consumes; both must agree on frame positions. Any change to 2.4 breaks this test by design.
- **Integration smoke test:** a scripted run — create project → upload fixtures → process → assert `status=ready` → fetch CDL → export → assert FCPXML validates.
- **Manual gates (cannot be automated):** "opens populated in Resolve" (8.2) and "no visible stutter / LUT visibly works" (7.1, 7.3) are human-verified and explicitly listed as such in their Definitions of Done.
- **Per-stage rule:** a stage's PR may not merge unless its Definition-of-Done checks pass. Treat the DoD as the acceptance criteria for the AI agent's work on that stage.

---

*End of specification.*

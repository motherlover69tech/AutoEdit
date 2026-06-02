# Source Documents Review

## Imported files

- `docs/source/multicam_autoedit_spec.md`
- `docs/source/multicam_ui_style_guide.html`

## Technical spec summary

AUTOEDIT is a staged, modular system for interview multicam auto-editing:

1. **Ingest & normalisation** — project creation, chunked upload, probe/channel mapping, audio sync, proxy generation, authenticated Range streaming.
2. **Audio analysis & VAD** — loudness envelopes, noise floor, thresholds, speaking intervals, activity timeline, program audio mixdown.
3. **Transcription & AI logging** — per-speaker transcription, topic segmentation, conciseness grading, reporting JSON.
4. **Auto-cut engine** — deterministic CDL generation from activity timeline and rules.
5. **Review player** — remote-capable multicam player, audio-master sync, metadata timeline, LUT, notes.
6. **Export** — CDL validation and FCPXML generation for DaVinci Resolve.
7. **Generative features** — natural-language sub-edits and YouTube title generation.

## Locked contracts from spec Section 2

These are integration boundaries and should not be changed unilaterally:

- Storage layout under `/data/<project_id>/`.
- MySQL schema in Section 2.2.
- Env/config names and defaults in Section 2.3.
- CDL JSON contract in Section 2.4.
- Job lifecycle semantics in Section 2.5.

## Mandatory security requirements

Because the app will be internet-accessible:

- TLS termination at the proxy.
- Authentication required for every route except health/ACME.
- Session cookies signed and httpOnly.
- Rate limiting/brute-force protection on auth and upload.
- CORS/origin checks locked to `PUBLIC_DOMAIN`.
- Media served only behind auth.
- Range requests supported for proxies/program audio.
- Upload content and notes are untrusted; validate/sanitise accordingly.
- Never pass user-supplied paths into shell commands.

## UI/style guide summary

The UI uses the Voices Media design system adapted for a dark editing application:

- Brand core: Ink `#0F0F0E`, Parchment `#F7F4EF`, Signal Red `#D43B2F`.
- Product surfaces: dark panels/cards/inputs with warm hairline borders.
- Typography:
  - DM Serif Display for headings/wordmark.
  - IBM Plex Sans for readable UI/body.
  - IBM Plex Mono for labels, timecode, thresholds, and machine-truth values.
- Red is rationed: primary action, presenter/live-cut/cut-suggestion semantics — not decoration.
- Fixed semantic timeline colours:
  - Presenter: `#D43B2F`
  - Interviewee: `#3FA7A0`
  - Wide: `#C9A227`
  - Overlap: `#8C5BD6`
- Product flow: Sign in → Create & ingest → Process → Review → Refine & export.
- Interface voice: direct, spare, no hype, concrete progress.

## Main risks

| Risk | Required mitigation |
| --- | --- |
| Choppy playback | Short-GOP silent proxies, Range streaming, ping-pong video elements, WAN quality tier |
| Angle drift | Audio-derived sync offsets, integer-ms master timeline, audio-master player drift correction |
| Blank Resolve import | CDL validator, exact rational FCPXML timing, source-file validation, real Resolve manual gate |
| LUT failure | Parse `.cube` into WebGL 3D texture over flat proxy |
| Public exposure | TLS/auth/rate limiting/CORS/authenticated media streaming |

## Recommended build order

Follow Appendix A from the spec. First stages:

1. Stage 3.1 — Project + DB bootstrap.
2. Stage 7.0 — Auth gate + reverse proxy.
3. Stage 3.2 — Chunked upload.
4. Stage 3.3 — Probe + channel mapping.
5. Stage 3.4 — Channel extraction + audio sync.
6. Stage 3.5 / 3.5b — Proxy tiers.
7. Stage 3.6 — Range streaming.

## Review conclusion

The provided files are sufficient to start implementation. The most important setup need is persistent project discipline: every future session should update handoff, backlog, and testing docs before stopping.

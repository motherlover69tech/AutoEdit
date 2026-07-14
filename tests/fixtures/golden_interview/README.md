# Golden Interview Fixture Manifest

This directory is the **Phase 0 scaffold** for the WhisperX speaker-aware AI
roadmap. It does not contain media and is not an accepted benchmark yet.

## Privacy and storage

Real interview excerpts may contain personal or confidential speech. Do not commit
source media, transcripts, names, private paths, or credentials here. Store
consent-cleared fixtures on a trusted host and supply the root only at runtime:

```bash
AUTOEDIT_GOLDEN_MEDIA_ROOT=/secure/autoedit-fixtures \
  env -u VIRTUAL_ENV uv run pytest tests/integration/test_whisperx_golden_media.py -q
```

The external root should eventually contain at least three 3–10 minute excerpts
covering alternating speech, cross-mic bleed, interruption/overlap, room noise,
quiet speech, laughter/coughs, and off-camera speech. Use opaque fixture IDs in
tracked manifests.

## Current state

The files under `expected/` intentionally contain `status: not_labeled` and empty
arrays. They are structural placeholders, **not expected production output** and
must not be used to pass an acceptance test. Before enabling WhisperX as speaker
authority:

1. confirm privacy/consent and the secure fixture location;
2. label uncertain boundaries explicitly;
3. capture the current VAD/activity/CDL baseline;
4. record measured speaker-turn, overlap, timestamp, transcript, and cut metrics;
5. set acceptance thresholds from that observed baseline; and
6. add an opt-in integration test that skips unless the external root is supplied.

See `docs/ai/whisperx-evaluation-protocol.md`.

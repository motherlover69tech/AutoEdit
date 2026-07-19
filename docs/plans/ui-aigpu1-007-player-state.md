# UI-AIGPU1-007 review-player state behavior

The review player presents three plain-language status fields below the video: analysis source, speaker-mapping status, and safety state. The active shot-reason card remains the authoritative per-shot explanation; unresolved, low-confidence, overlap, off-camera, and missing-wide conditions are read from machine-readable projection metadata rather than inferred from editorial prose.

Player safety behavior:

- The player accepts only integer-millisecond clips that begin at master time zero, have positive duration, non-negative source time, and are contiguous. Empty, malformed, gapped, or out-of-order cuts fail visibly through the player status error path rather than being clipped or repaired.
- A time outside the cut returns no clip. The player does not reuse the final clip as an arbitrary fallback.
- A cut-regeneration response is validated before replacing the displayed clip list. A malformed candidate leaves the current authoritative selection in place and reports regeneration failure.
- Safe-wide explanations are visible as `Unresolved speaker — wide chosen to avoid a wrong close-up`, `Low confidence — wide chosen until identity is confirmed`, `Off-camera or uncertain — wide chosen safely`, or `Overlap — wide chosen for simultaneous speech`.
- The player continues to use program audio as its master clock and silent proxy URLs for video. No VAD artifact, current selected cut, or persisted clip metadata is mutated by these UI checks.

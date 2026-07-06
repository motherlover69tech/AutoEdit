from __future__ import annotations

from typing import Any

from autoedit.config import Settings
from autoedit.llm_client import get_llm_client


async def review_cut_quality(
    cdl: dict[str, Any],
    transcript_segments: list[dict[str, Any]],
    activity_timeline: list[dict[str, Any]],
    angle_labels: dict[str, str],
    settings: Settings,
) -> dict[str, Any] | None:
    """Review a generated cut against the transcript and activity timeline.

    Identifies potential issues:
    - Wide shots that interrupt mid-sentence
    - Silence holds that are too long
    - Cuts that happen at unnatural points
    - Missing coverage of key speakers

    Returns a review dict with issues and suggestions, or None if LLM unavailable.
    """
    if not transcript_segments or not cdl.get("clips"):
        return None

    client = get_llm_client(settings)

    # Build clip summary
    clips = cdl["clips"]
    clip_summaries = []
    for i, clip in enumerate(clips):
        angle_id = clip.get("angle_id", "")
        angle_label = angle_labels.get(angle_id, angle_id)
        timeline_in = clip.get("timeline_in_ms", 0)
        dur = clip.get("dur_ms", 0)
        reason = clip.get("reason", "")
        start_min = timeline_in // 60000
        start_sec = (timeline_in % 60000) // 1000
        end_min = (timeline_in + dur) // 60000
        end_sec = ((timeline_in + dur) % 60000) // 1000
        clip_summaries.append(
            f"  Clip {i+1}: {angle_label} [{start_min:02d}:{start_sec:02d}-{end_min:02d}:{end_sec:02d}] ({dur/1000:.1f}s) - {reason}"
        )

    # Build transcript summary around cut points
    transcript_by_time = {}
    for seg in transcript_segments:
        for t in range(seg["start_ms"], seg["end_ms"], 5000):  # Every 5 seconds
            key = t // 5000
            transcript_by_time[key] = seg["text"][:200]

    # Build activity summary
    activity_summaries = []
    for act in activity_timeline:
        start_min = act["start_ms"] // 60000
        start_sec = (act["start_ms"] % 60000) // 1000
        end_min = act["end_ms"] // 60000
        end_sec = (act["end_ms"] % 60000) // 1000
        active = act.get("active", [])
        activity_summaries.append(
            f"  [{start_min:02d}:{start_sec:02d}-{end_min:02d}:{end_sec:02d}] Active: {', '.join(active) if active else 'SILENCE'}"
        )

    system_prompt = """You are an expert video editor reviewing an auto-generated multicam cut.
Given the cut decision list (CDL), transcript, and speaker activity timeline, identify issues.

Look for:
1. Wide shots interrupting mid-sentence (speaker was talking, cut to wide)
2. Silence holds too long (>8s on same angle with no one speaking)
3. Cuts at unnatural points (mid-word, mid-sentence)
4. Missing speaker coverage (speaker active but not shown)
5. Too-rapid cutting (jitter) - clips <1.2s that could be merged
6. Overlap handling - when 2 speakers talk, should be wide

Return ONLY valid JSON:
{
  "issues": [
    {
      "type": "wide_interrupt" | "long_silence" | "unnatural_cut" | "missing_speaker" | "jitter" | "overlap_not_wide",
      "severity": "high" | "medium" | "low",
      "clip_index": int,
      "time_ms": int,
      "description": "Human-readable description",
      "suggestion": "Specific fix suggestion"
    }
  ],
  "overall_rating": "good" | "needs_review" | "poor",
  "summary": "Brief overall assessment"
}"""

    user_prompt = f"""Cut Decision List ({len(clips)} clips):
{chr(10).join(clip_summaries)}

Speaker Activity Timeline:
{chr(10).join(activity_summaries)}

Transcript snippets available for context.

Review this cut for quality issues."""

    try:
        result = await client.chat(
            system=system_prompt,
            user=user_prompt,
            temperature=0.2,
            format_json=True,
            max_tokens=2000,
        )

        if isinstance(result, dict) and "issues" in result:
            # Validate and normalize
            issues = []
            for issue in result.get("issues", []):
                if all(k in issue for k in ("type", "severity", "clip_index", "time_ms", "description")):
                    issue["clip_index"] = int(issue["clip_index"])
                    issue["time_ms"] = int(issue["time_ms"])
                    issues.append(issue)

            return {
                "issues": issues,
                "overall_rating": result.get("overall_rating", "needs_review"),
                "summary": result.get("summary", ""),
            }
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"LLM cut review failed: {e}")

    return None


def format_cut_review_for_ui(review: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Convert cut review to UI-friendly format."""
    if not review or not review.get("issues"):
        return []

    ui_notes = []
    for issue in review["issues"]:
        kind = "cut_suggestion" if issue["severity"] in ("high", "medium") else "note"
        ui_notes.append({
            "t_ms": issue["time_ms"],
            "body": f"[{issue['type'].replace('_', ' ').title()}] {issue['description']}. Suggestion: {issue.get('suggestion', 'Review this cut.')}",
            "kind": kind,
        })

    return ui_notes
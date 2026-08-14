export const SPEAKER_STATUS_BADGES = Object.freeze({
  confirmed: { label: 'Confirmed', tone: 'ok' },
  suggested: { label: 'Suggested', tone: 'suggested' },
  needs_confirmation: { label: 'Needs confirmation', tone: 'neutral' },
  stale: { label: 'Stale', tone: 'warn' },
  conflict: { label: 'Conflict — Wide', tone: 'err' },
  revalidation_required: { label: 'Revalidation required', tone: 'warn' },
});

export function speakerBadge(status) {
  return SPEAKER_STATUS_BADGES[status] || SPEAKER_STATUS_BADGES.needs_confirmation;
}

export function batchConfirmationSaveDisabled(rows) {
  if (!Array.isArray(rows) || rows.length === 0) return true;
  if (rows.some((row) => !row.speakerId || !row.cameraId || Number(row.snippetCount) < 2 || !row.acknowledged)) return true;
  const speakers = rows.map((row) => row.speakerId);
  const cameras = rows.map((row) => row.cameraId);
  return new Set(speakers).size !== rows.length || new Set(cameras).size !== rows.length;
}

export function confirmationExpectedVersion(confirmation) {
  return confirmation?.is_current ? (confirmation.version ?? null) : null;
}

export function confidenceLabel(value) {
  return value == null || !Number.isFinite(Number(value))
    ? 'Not reported'
    : `${Math.round(Number(value) * 100)}% reported confidence`;
}

export function regenerationOutcome(status, detail = '') {
  if (status >= 200 && status < 300) return 'Candidate created. Open the review player to preview and save it; your current cut is unchanged.';
  if (status === 409) return 'Regeneration blocked (409): complete current confirmations or reload after a conflict.';
  return `Regeneration failed: ${String(detail)}`;
}

export const HONEST_STATES = Object.freeze([
  'loading', 'no AI run yet', 'Gate 1 not accepted', 'worker/diarization failed',
  'no anonymous turns', 'needs confirmation', 'suggested', 'confirmed', 'stale',
  'saving', 'saved', 'save conflict 409', 'regenerating', 'regenerate failed', 'network error',
]);

export function honestStateLabel(state) {
  return HONEST_STATES.includes(state) ? state : 'network error';
}

export function safeText(value) {
  return String(value ?? '').replace(/[&<>\"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}

import assert from 'node:assert/strict';
import {
  chooseMediaUrl,
  createManualOverrideState,
  createPlayerStateStore,
  analysisStatusDisplay,
  findClipAtTime,
  findNextClip,
  formatTimelineMs,
  frameDurationSeconds,
  msToPercent,
  needsDriftCorrection,
  parseCubeLUT,
  shotReasonDisplay,
  playbackVideoTimeForAngle,
  playbackVideoTimeForClip,
  percentToMs,
  timelineMsFromAudio,
  videoTimeForAngle,
  videoTimeForClip,
  validateContiguousClips,
  normalizeProjectedActivity,
  activityStatusDisplay,
  validateMasterTimeSpans,
} from '../src/autoedit/web/player.js';

const clips = [
  { angle_id: 'a', timeline_in_ms: 0, src_in_ms: 100, dur_ms: 1000 },
  { angle_id: 'b', timeline_in_ms: 1000, src_in_ms: 900, dur_ms: 1000 },
];

assert.equal(findClipAtTime(clips, 0).angle_id, 'a');
assert.equal(findClipAtTime(clips, 999).angle_id, 'a');
assert.equal(findClipAtTime(clips, 1000).angle_id, 'b');
assert.equal(findNextClip(clips, 500).angle_id, 'b');
assert.equal(findNextClip(clips, 1500), null);
assert.equal(findClipAtTime(clips, 2500), null);
assert.deepEqual(validateContiguousClips(clips), { totalDurationMs: 2000 });
assert.throws(() => validateContiguousClips([{ ...clips[1], timeline_in_ms: 10 }]), /non-contiguous/);
assert.throws(() => validateContiguousClips([]), /empty/);
assert.throws(() => validateContiguousClips([{ ...clips[0], src_in_ms: -1 }]), /malformed/);
assert.throws(() => validateContiguousClips([{ ...clips[0], dur_ms: 0 }]), /malformed/);
assert.throws(() => validateContiguousClips([{ ...clips[0], timeline_in_ms: 0.5 }]), /malformed/);
const projected = normalizeProjectedActivity({
  total_duration_ms: 2000,
  timeline: [
    { start_ms: 0, end_ms: 1000, active: ['speaker-a'], mapping_status: 'confirmed', authority_status: 'confirmed' },
    { start_ms: 1000, end_ms: 2000, active: [], mapping_status: 'unresolved', authority_status: 'unresolved', unresolved: true },
  ],
});
assert.equal(projected.timeline[1].unresolved, true);
assert.equal(activityStatusDisplay({ authority_status: 'confirmed' }).label, 'Confirmed authority');
assert.equal(activityStatusDisplay({ unresolved: true }).tone, 'unresolved');
assert.equal(activityStatusDisplay({ low_confidence: true }).tone, 'low-confidence');
assert.equal(activityStatusDisplay({ overlap: true }).tone, 'overlap');
assert.equal(activityStatusDisplay({ off_camera: true }).tone, 'off-camera');
assert.equal(activityStatusDisplay({ missing_wide: true }).tone, 'missing-wide');
// Suggested mappings are audit-only: they cannot become authority or select
// an arbitrary close-up.
assert.equal(
  activityStatusDisplay({
    authority_status: 'unresolved',
    unresolved: true,
    suggested_mapping: { speaker_id: 'speaker-a', angle_id: 'closeup-a' },
  }).status,
  'unresolved',
);
assert.equal(findClipAtTime([{ ...clips[0], suggested_angle_id: 'arbitrary-closeup' }], 500).angle_id, 'a');
assert.equal(validateMasterTimeSpans(projected.timeline, 2000), true);
assert.throws(() => validateMasterTimeSpans([{ start_ms: 0, end_ms: 900 }], 2000), /cover/);
assert.throws(() => normalizeProjectedActivity({ total_duration_ms: 2000, timeline: [{ ...projected.timeline[1], start_ms: 500 }] }), /malformed/);
assert.throws(() => normalizeProjectedActivity({ total_duration_ms: 2000, timeline: [{ ...projected.timeline[1], end_ms: 2500 }] }), /malformed/);
assert.throws(() => normalizeProjectedActivity({ total_duration_ms: 2000, timeline: [] }), /cover/);
const stateStore = createPlayerStateStore({ cut: { clips }, projected_activity: null });
const priorCut = stateStore.state.cut;
stateStore.replaceProjected(projected);
assert.equal(stateStore.state.cut, priorCut);
assert.deepEqual(stateStore.state.projected_activity, projected);
stateStore.failProjected(new Error('refresh unavailable'));
assert.equal(stateStore.state.cut, priorCut);
assert.equal(stateStore.state.projected_activity, null);
assert.match(stateStore.projectedError, /refresh unavailable/);
assert.deepEqual(
  analysisStatusDisplay({ source: 'whisperx', mapping_status: 'needs_confirmation' }, { projection: { unresolved: true } }),
  {
    source: 'WhisperX projected activity',
    mapping: 'Mapping needs confirmation',
    safety: 'Unresolved speaker — wide chosen to avoid a wrong close-up',
    tone: 'uncertain',
  },
);

assert.deepEqual(
  shotReasonDisplay({ reason_code: 'speaking', reason_label: 'Speaking', reason_detail: 'Peter' }),
  { label: 'Speaking', detail: 'Peter', tone: 'speaking' },
);
assert.deepEqual(
  shotReasonDisplay({ reason: 'periodic:wide' }),
  { label: 'Variety shot', detail: 'Breaks up a long-held shot', tone: 'variety' },
);
assert.deepEqual(
  shotReasonDisplay(null, true),
  { label: 'Manual override', detail: 'Automatic shot reason paused', tone: 'manual' },
);

assert.equal(timelineMsFromAudio(1.2344), 1234);
assert.equal(timelineMsFromAudio(1.2345), 1235);
assert.equal(videoTimeForClip(clips[1], 1250), 1.15);
// CDL src_in_ms is already sync-adjusted. Playback must not subtract the stored
// automatic sync offset again; only explicit manual preview nudges apply.
assert.equal(playbackVideoTimeForClip(clips[1], 1250, 0), 1.15);
assert.equal(playbackVideoTimeForClip(clips[1], 1250, 100), 1.05);
assert.equal(playbackVideoTimeForClip(clips[1], 1250, -100), 1.25);

const wideAngle = { id: 'wide', source_time_offset_ms: 31315 };
const intervieweeAutoClip = { angle_id: 'interviewee', timeline_in_ms: 397397, src_in_ms: 397397, dur_ms: 2919 };
// Manual Wide preview must stay on Wide's timeline-derived source time even when
// the auto cut at the same timeline position is an Interviewee clip.
assert.equal(videoTimeForAngle(wideAngle, 397397), 428.712);
assert.equal(playbackVideoTimeForAngle(wideAngle, 397397, 0), 428.712);
assert.equal(videoTimeForClip(intervieweeAutoClip, 397397), 397.397);

const oneFrame = frameDurationSeconds(24000, 1001);
assert.ok(needsDriftCorrection(1.0, 1.0 + oneFrame + 0.001, oneFrame));
assert.ok(!needsDriftCorrection(1.0, 1.0 + oneFrame / 2, oneFrame));

const angleWithLow = { proxy_url: '/main.mp4', proxy_low_url: '/low.mp4' };
const angleMainOnly = { proxy_url: '/main.mp4' };
assert.equal(chooseMediaUrl(angleWithLow, 'proxy_low'), '/low.mp4');
assert.equal(chooseMediaUrl(angleMainOnly, 'proxy_low'), '/main.mp4');
assert.equal(chooseMediaUrl(angleWithLow, 'proxy'), '/main.mp4');

const override = createManualOverrideState();
assert.equal(override.resolve('auto-a'), 'auto-a');
assert.equal(override.force('manual-b'), 'manual-b');
assert.equal(override.resolve('auto-a'), 'manual-b');
assert.equal(override.clear(), null);
assert.equal(override.resolve('auto-a'), 'auto-a');

// ── Timeline helpers ──────────────────────────────────────────

assert.equal(formatTimelineMs(0), '0:00');
assert.equal(formatTimelineMs(5000), '0:05');
assert.equal(formatTimelineMs(65000), '1:05');
assert.equal(formatTimelineMs(125000), '2:05');
assert.equal(formatTimelineMs(3600000), '60:00');

const totalMs = 4000;
assert.equal(msToPercent(0, totalMs), 0);
assert.equal(msToPercent(2000, totalMs), 50);
assert.equal(msToPercent(4000, totalMs), 100);
assert.equal(percentToMs(0, totalMs), 0);
assert.equal(percentToMs(50, totalMs), 2000);
assert.equal(percentToMs(100, totalMs), 4000);
assert.equal(msToPercent(0, 0), 0);
assert.equal(percentToMs(50, 0), 0);
assert.equal(percentToMs(-5, totalMs), 0);

// ── LUT parser ────────────────────────────────────────────────

const MINI_CUBE =
  'TITLE "Mini LUT"\n' +
  'LUT_3D_SIZE 2\n' +
  '0.0 0.0 0.0\n' +
  '0.0 0.0 1.0\n' +
  '0.0 1.0 0.0\n' +
  '0.0 1.0 1.0\n' +
  '1.0 0.0 0.0\n' +
  '1.0 0.0 1.0\n' +
  '1.0 1.0 0.0\n' +
  '1.0 1.0 1.0\n';

const result = parseCubeLUT(MINI_CUBE);
assert.equal(result.size, 2);
assert.equal(result.title, 'Mini LUT');
assert.equal(result.data.length, 2 * 2 * 2 * 3); // 24 floats
assert.equal(result.data[0], 0.0);
assert.equal(result.data[1], 0.0);
assert.equal(result.data[2], 0.0);
assert.equal(result.data[21], 1.0);
assert.equal(result.data[22], 1.0);
assert.equal(result.data[23], 1.0);

// Comments and blank lines
const CUBE_WITH_COMMENTS =
  '# This is a comment\n' +
  'TITLE "Test"\n' +
  'LUT_3D_SIZE 2\n' +
  '# another comment\n' +
  '\n' +
  '0.5 0.5 0.5\n' +
  '0.5 0.5 0.5\n' +
  '0.5 0.5 0.5\n' +
  '0.5 0.5 0.5\n' +
  '0.5 0.5 0.5\n' +
  '0.5 0.5 0.5\n' +
  '0.5 0.5 0.5\n' +
  '0.5 0.5 0.5\n';
const result2 = parseCubeLUT(CUBE_WITH_COMMENTS);
assert.equal(result2.size, 2);
assert.equal(result2.title, 'Test');
assert.equal(result2.data.length, 24);

// No title
const NO_TITLE = 'LUT_3D_SIZE 2\n0.0 0.0 0.0\n0.0 0.0 1.0\n0.0 1.0 0.0\n0.0 1.0 1.0\n1.0 0.0 0.0\n1.0 0.0 1.0\n1.0 1.0 0.0\n1.0 1.0 1.0\n';
const result3 = parseCubeLUT(NO_TITLE);
assert.equal(result3.title, '');

// Missing LUT_3D_SIZE
try {
  parseCubeLUT('TITLE "Bad"\n0.0 0.0 0.0\n');
  assert.fail('Should have thrown');
} catch (e) {
  assert.ok(e.message.includes('LUT_3D_SIZE'));
}

console.log('All player logic + timeline + LUT + angle-LUT tests passed');

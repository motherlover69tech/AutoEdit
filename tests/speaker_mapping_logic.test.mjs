import assert from 'node:assert/strict';
import {
  speakerBadge,
  suggestedPrefill,
  confirmationSaveDisabled,
  confidenceLabel,
  regenerationOutcome,
  safeText,
  HONEST_STATES,
  honestStateLabel,
} from '../src/autoedit/web/speaker_mapping_logic.js';

assert.deepEqual(speakerBadge('confirmed'), { label: 'Confirmed', tone: 'ok' });
assert.deepEqual(speakerBadge('suggested'), { label: 'Suggested', tone: 'suggested' });
assert.equal(speakerBadge('worker_failed').label, 'Needs confirmation');
assert.deepEqual(suggestedPrefill({ status: 'suggested', suggested_speaker_id: 'Alice', suggested_camera_id: 'cam-a' }), { speakerId: 'Alice', cameraId: 'cam-a' });
assert.deepEqual(suggestedPrefill({ status: 'suggested', suggested_speaker_id: 'Alice', suggested_camera_id: null }), { speakerId: 'Alice', cameraId: '' });
assert.equal(confirmationSaveDisabled({ speakerId: 'Alice', cameraId: 'cam-a', snippetCount: 1 }), true);
assert.equal(confirmationSaveDisabled({ speakerId: 'Alice', cameraId: 'cam-a', snippetCount: 2 }), false);
assert.equal(confirmationSaveDisabled({ speakerId: '', cameraId: 'cam-a', snippetCount: 2 }), true);
assert.equal(confidenceLabel(0.876), '88% reported confidence');
assert.equal(confidenceLabel(null), 'Not reported');
assert.equal(confidenceLabel(undefined), 'Not reported');
for (const status of HONEST_STATES) assert.equal(honestStateLabel(status), status);
assert.equal(honestStateLabel('unknown'), 'network error');
assert.match(regenerationOutcome(201), /review player/);
assert.match(regenerationOutcome(409), /409/);
assert.match(regenerationOutcome(500, 'network failure'), /network failure/);
assert.equal(safeText('<script>alert(1)</script>'), '&lt;script&gt;alert(1)&lt;/script&gt;');
console.log('Phase 6 speaker mapping logic tests passed');

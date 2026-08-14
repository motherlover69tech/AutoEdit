import assert from 'node:assert/strict';
import {
  speakerBadge,
  batchConfirmationSaveDisabled,
  confirmationExpectedVersion,
  confidenceLabel,
  regenerationOutcome,
  safeText,
  HONEST_STATES,
  honestStateLabel,
} from '../src/autoedit/web/speaker_mapping_logic.js';

assert.deepEqual(speakerBadge('confirmed'), { label: 'Confirmed', tone: 'ok' });
assert.deepEqual(speakerBadge('suggested'), { label: 'Suggested', tone: 'suggested' });
assert.equal(speakerBadge('worker_failed').label, 'Needs confirmation');
const complete = [
  { speakerId: 'Alice', cameraId: 'cam-a', snippetCount: 2, acknowledged: true },
  { speakerId: 'Bob', cameraId: 'cam-b', snippetCount: 2, acknowledged: true },
];
assert.equal(batchConfirmationSaveDisabled(complete), false);
assert.equal(batchConfirmationSaveDisabled([{ ...complete[0] }, { ...complete[1], speakerId: '' }]), true);
assert.equal(batchConfirmationSaveDisabled([{ ...complete[0] }, { ...complete[1], speakerId: 'Alice' }]), true);
assert.equal(batchConfirmationSaveDisabled([{ ...complete[0] }, { ...complete[1], acknowledged: false }]), true);
assert.equal(confirmationExpectedVersion({ is_current: true, version: 3 }), 3);
assert.equal(confirmationExpectedVersion({ is_current: false, version: 3 }), null);
assert.equal(confirmationExpectedVersion(null), null);
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

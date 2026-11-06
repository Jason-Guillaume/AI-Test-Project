import assert from 'node:assert/strict';
import test from 'node:test';
import { hasReviewTime, reviewTimeLabel } from '../src/features/asr-evaluation/components/reviewEvidenceTime.mjs';

test('review evidence omits invalid and absent times without rendering NaN', () => {
  for (const value of [null, undefined, Number.NaN, Number.POSITIVE_INFINITY, '59000']) {
    assert.equal(hasReviewTime(value), false);
    assert.equal(reviewTimeLabel(value), '—');
  }
  assert.equal(hasReviewTime(59_000), true);
  assert.equal(reviewTimeLabel(59_000), '00:59');
});

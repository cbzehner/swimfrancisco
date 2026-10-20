import test from 'node:test';
import assert from 'node:assert/strict';
import { automationHealth } from '../../scripts/lib/schedule-health.mjs';

const now = '2026-10-20T20:00:00Z';
const job = (name, completed_at, conclusion = 'success') => ({ name, completed_at, conclusion });
const health = jobs => automationHealth({ workflowState: 'active', enabled: 'true', now, jobs });

test('an unchanged daily detection and weekly extraction are healthy', () => {
  const report = health([job('detect', '2026-10-20T16:05:00Z'), job('extract', '2026-10-19T17:00:00Z')]);
  assert.deepEqual(report.issues, []);
  assert.equal(report.last_extraction_at, '2026-10-19T17:00:00Z');
});

test('successful detection cannot hide a broken full extraction', () => {
  assert.deepEqual(health([job('detect', '2026-10-20T16:05:00Z'),
    job('extract', '2026-10-19T17:00:00Z', 'failure')]).issues.map(issue => issue.code), ['extraction_overdue']);
});

test('skipped and future jobs cannot provide a heartbeat', () => {
  const report = health([job('extract', '2026-10-20T17:00:00Z', 'skipped'), job('detect', '2026-10-21T17:00:00Z')]);
  assert.deepEqual(report.issues.map(issue => issue.code), ['detection_overdue', 'extraction_overdue']);
});

test('disabled workflow and variable are explicit problems', () => {
  const report = automationHealth({ workflowState: 'disabled_inactivity', enabled: '', now,
    jobs: [job('extract', '2026-10-20T17:00:00Z')] });
  assert.deepEqual(report.issues.map(issue => issue.code), ['workflow_disabled', 'automation_disabled']);
});

test('a recent full run also satisfies daily detection', () => {
  assert.deepEqual(health([job('extract', '2026-10-20T17:00:00Z')]).issues, []);
});

test('coverage and reporting jobs do not count as source checks', () => {
  assert.equal(health([job('coverage', '2026-10-20T17:00:00Z'), job('report', '2026-10-20T17:00:00Z')]).issues.length, 2);
});

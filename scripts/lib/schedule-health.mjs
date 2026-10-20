const HOUR = 60 * 60 * 1000;

export function automationHealth({ workflowState, enabled, jobs, now = new Date() }) {
  const instant = new Date(now).getTime();
  if (!Number.isFinite(instant)) throw new Error('Invalid watchdog clock');
  const successes = jobs.filter(job => job.conclusion === 'success'
    && Number.isFinite(Date.parse(job.completed_at)) && Date.parse(job.completed_at) <= instant);
  const latest = names => successes.filter(job => names.includes(job.name))
    .map(job => job.completed_at).sort().at(-1) || null;
  const lastDetection = latest(['detect', 'extract']);
  const lastExtraction = latest(['extract']);
  const issues = [];
  if (workflowState !== 'active') issues.push({ code: 'workflow_disabled', message: 'The schedule workflow is not active.' });
  if (enabled !== 'true') issues.push({ code: 'automation_disabled', message: 'SCHEDULES_AUTOMATION_ENABLED is not true.' });
  if (!lastDetection || instant - Date.parse(lastDetection) > 36 * HOUR) {
    issues.push({ code: 'detection_overdue', message: 'No successful scheduled source check in the last 36 hours.' });
  }
  if (!lastExtraction || instant - Date.parse(lastExtraction) > 8 * 24 * HOUR) {
    issues.push({ code: 'extraction_overdue', message: 'No successful scheduled full extraction in the last eight days.' });
  }
  return { checked_at: new Date(instant).toISOString(), last_detection_at: lastDetection,
    last_extraction_at: lastExtraction, issues };
}

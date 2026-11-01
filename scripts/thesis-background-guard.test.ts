import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const button = readFileSync('components/research/ThesisGenerateButton.tsx', 'utf8');
const scheduler = readFileSync('data-engine/app/workers/scheduler.py', 'utf8');
const route = readFileSync('data-engine/app/api/routes/thesis.py', 'utf8');

test('F359: remount/focus recovers the server job, never starts it again', () => {
    assert.match(button, /await getLatestThesisJob\(ticker\)/);
    assert.match(button, /addEventListener\('visibilitychange', onVisible\)/);
    assert.match(button, /addEventListener\('focus', recover\)/);
    assert.match(button, /\['queued', 'running', 'retrying', 'dispatch_failed'\]/);
    assert.match(button, /if \(busy \|\| startingRef.current\) return/);
    assert.match(button, /if \(disposed\) return/);
    assert.doesNotMatch(button, /localStorage|sessionStorage/);
});

test('F359: dispatch recovery runs server-side, enqueue does no enrichment', () => {
    assert.match(scheduler, /_register\(scheduler, reconcile_thesis_dispatches, "interval",\s*job_id="thesis_dispatch_recovery", minutes=1\)/);
    const enqueue = route.slice(route.indexOf('def generate_thesis_async'), route.indexOf('@router.get("/jobs/{run_id}", response_model=ThesisJobStatusOut)'));
    assert.doesNotMatch(enqueue, /ensure_company_stub/);
    assert.match(route, /@router.get\("\/jobs", response_model=ThesisLatestJobOut\)/);
});

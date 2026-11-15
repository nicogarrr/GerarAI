"""Summarize only safe JSONL probe fields by Playwright case/attempt windows."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def summarize(events):
    starts = {}
    ends = [e for e in events if e['event'] == 'end']
    reports = []
    markers = [e for e in events if e['event'] == 'marker']
    paired = {(e['case_id'], e['attempt']) for e in markers if e['action'] == 'end'}
    unclosed = [e for e in markers if e['action'] == 'start' and (e['case_id'], e['attempt']) not in paired]
    for opened in unclosed:
        last = events[-1]
        markers.append({**opened, 'action': 'end', 'monotonic': last['monotonic'],
                        'inflight': last.get('inflight', opened['inflight']), 'incomplete_window': True})
    for marker in markers:
        key = (marker['case_id'], marker['attempt'])
        if marker['action'] == 'start':
            starts[key] = marker
            continue
        initial = starts.pop(key, None)
        if initial is None:
            continue
        begin, end = initial['monotonic'], marker['monotonic']
        window = [e for e in events if begin <= e['monotonic'] <= end]
        attempts = [e for e in window if e['event'] == 'attempt']
        request_ids = {e['request_id'] for e in attempts}
        completed = [e for e in ends if e['request_id'] in request_ids]
        statuses = Counter(e['status'] for e in completed)
        counts = [initial['inflight'], marker['inflight'], *(e['inflight'] for e in window if 'inflight' in e)]
        overlap = [e for e in ends if e['monotonic_start'] < begin < e['monotonic_end']]
        reports.append({
            'case_id': key[0], 'attempt': key[1], 'monotonic_start': begin, 'monotonic_end': end,
            'incomplete_window': marker.get('incomplete_window', False),
            'total_started': len(attempts), 'completed': len(completed),
            '2xx': sum(count for status, count in statuses.items() if 200 <= status < 300),
            '429': statuses[429], '503': statuses[503], 'status_counts': dict(statuses),
            'peak_admitted': max(c['admitted_global'] for c in counts),
            'peak_attempted': max(c['attempted_global'] for c in counts),
            'peak_admitted_tenant': max((c['admitted_tenant'] or 0 for c in counts), default=0),
            'peak_attempted_tenant': max((c['attempted_tenant'] or 0 for c in counts), default=0),
            'inflight_initial': initial['inflight'], 'inflight_final': marker['inflight'],
            'carry_in_observed': len(overlap),
            'carry_out': sum(e['monotonic_end'] > end for e in completed)+len(request_ids-{e['request_id'] for e in completed}),
            'paths': dict(Counter(f"{e['method']} {e['path']}" for e in attempts)),
            'tenants': sorted({e['tenant'] for e in attempts}),
        })
    return {'cases': reports, 'unclosed_markers': [{'case_id': e['case_id'], 'attempt': e['attempt']} for e in unclosed],
            'total_attempts': sum(e['event'] == 'attempt' for e in events),
            'unclosed_requests': len({e['request_id'] for e in events if e['event'] == 'attempt'}-
                                     {e['request_id'] for e in ends}),
            'scope': 'Backend admission attempts include browser fetches, Next SSR, server actions and E2E setup reads. '
                     'Windows are time-based, not a claim of causal browser attribution; initial/final/carry expose overlap.'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    events = [json.loads(line) for line in args.source.read_text().splitlines() if line.strip()]
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    args.destination.write_text(json.dumps(summarize(events), indent=2)+'\n')
    print(f'Admission summary written to {args.destination}; {len(events)} safe events')


if __name__ == '__main__':
    main()

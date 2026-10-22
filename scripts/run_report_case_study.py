"""Capture an isolated report example, including an explicitly automated review.

This is software acceptance, not a human quality review or an M6 annotation.
No graph writes or live graph queries are performed. Existing outputs are refused.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from run_demo_acceptance import Acceptance, DemoTime, DAY, SEED, service, tracking, app, TestClient


class ReportAcceptance(Acceptance):
    def __init__(self, client):
        super().__init__(client)
        self.trace = {}

    def post(self, path, body=None, status=200):
        if path == '/api/case_close':
            body = {**body, 'review_requested': True,
                    'review_reason': 'Automated report scenario tests the review gate; no human assessment is claimed.'}
        result = super().post(path, body, status)
        if path == '/api/case_close' and 'registered' not in self.trace:
            self.trace['registered'] = result
            self.check('explicit review request remains pending', result['review_status'] == 'pending')
            super().post('/api/dispatch/reshipments/preview', {'run_id': result['run_id']}, status=422)
            self.check('pending review blocks replacement preview', True)
            reviewed = super().post(f"/api/runs/{result['run_id']}/review", {
                'command_id': 'report-automated-review',
                'expected_version': result['workflow_version'],
                'disposition': 'scrap',
                'reviewer': 'AUTOMATED-DEMO-NOT-A-HUMAN',
                'reason': 'Scripted acceptance of the prototype rule result to exercise downstream state transitions; not clinical or independent human review.',
            })
            self.trace['reviewed'] = reviewed
            self.check('review preserves original rule and sets effective disposition',
                       reviewed['disposition'] == result['disposition'] == 'scrap'
                       and reviewed['effective_disposition'] == 'scrap')
            return reviewed
        if path == '/api/dispatch/reshipments/preview' and status == 200:
            self.trace['replacement_preview'] = result
        if path == '/api/dispatch/reshipments' and status == 200:
            self.trace['replacement_accepted'] = result
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    DemoTime.instant = datetime.datetime(2026, 10, 1, 9)
    with patch.object(service, 'DISPATCH_DATABASE_URL', str(args.output / 'dispatch.sqlite3')), \
         patch.object(service, 'RUNS_FILE', args.output / 'runs.jsonl'), \
         patch.object(service, '_audit', lambda *a, **kw: None), \
         patch.object(service, 'write_case', lambda r: False), \
         patch.object(tracking, 'datetime', SimpleNamespace(datetime=DemoTime)), \
         TestClient(app) as client:
        a = ReportAcceptance(client)
        a.main_day()
        result = {'status': 'passed', 'operating_date': DAY, 'seed': SEED,
                  'review_mode': 'automated_demonstration_not_human',
                  'graph_mode': 'not_verified', 'check_count': len(a.checks),
                  'checks': a.checks, 'trace': a.trace, 'snapshots': a.snapshots,
                  'environment': {'python': platform.python_version(), 'platform': platform.platform(),
                                  'packages': {p: importlib.metadata.version(p) for p in ['fastapi', 'httpx', 'ortools', 'numpy', 'scikit-learn']}},
                  'source_sha256': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__), Path(__file__).with_name('run_demo_acceptance.py')]}}
        (args.output / 'report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(f"PASS: {len(a.checks)} checks; automated review; graph not verified")


if __name__ == '__main__':
    main()

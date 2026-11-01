import pytest

from app.services.propicks_radar_batch import ProviderThrottled, ScanBudget, scan_batch


class Clock:
    now = 0.0
    def __call__(self):
        return self.now
    def sleep(self, seconds):
        self.now += seconds


def run(ids=(1, 2, 3), **kwargs):
    clock = Clock()
    saved = []
    requests = []
    def fetch(i):
        requests.append((i, clock()))
        return {'company_id': i}
    result = scan_batch(ids, fetch_and_evaluate=kwargs.pop('fetch', fetch),
                        save_and_checkpoint=kwargs.pop('save', lambda i, row: saved.append((i, row))),
                        clock=clock, sleep=clock.sleep, **kwargs)
    return result, requests, saved


def test_bounded_ordered_deduplicated_and_paced():
    result, requests, saved = run([3, 1, 2, 2])
    assert requests == [(1, 0), (2, 1), (3, 2)]
    assert result == dict(status='completed', cursor=3, saved=3, remaining=0, duration_seconds=2)
    assert [i for i, _ in saved] == [1, 2, 3]


def test_resume_skips_committed_rows_and_honors_company_budget():
    result, requests, _ = run(after_id=1, budget=ScanBudget(max_companies=1))
    assert requests == [(2, 0)]
    assert result['cursor'] == 2 and result['remaining'] == 1
    assert result['status'] == 'company_budget'


def test_time_budget_accounts_for_next_delay_and_exhaustion():
    result, requests, _ = run(budget=ScanBudget(max_seconds=1))
    assert requests == [(1, 0)] and result['status'] == 'time_budget'
    clock = Clock()
    def slow(i):
        clock.now += 2
        return {}
    result = scan_batch([1, 2], fetch_and_evaluate=slow, save_and_checkpoint=lambda *a: None,
                        budget=ScanBudget(max_seconds=1), clock=clock, sleep=clock.sleep)
    assert result['saved'] == 1 and result['status'] == 'time_budget'


def test_throttling_does_not_checkpoint_or_retry_the_rejected_item():
    attempts = []
    def fetch(i):
        attempts.append(i)
        if i == 2:
            raise ProviderThrottled()
        return {}
    result, _, saved = run(fetch=fetch)
    assert attempts == [1, 2] and result['cursor'] == 1
    assert result['status'] == 'provider_throttled' and result['remaining'] == 2
    assert len(saved) == 1


def test_failed_persistence_is_never_claimed_as_success():
    def fail(*args):
        raise ValueError('save failed')
    with pytest.raises(ValueError, match='save failed'):
        run(save=fail)


def test_empty_resume_and_slow_provider_need_no_extra_sleep():
    assert run([], after_id=9)[0]['cursor'] == 9
    clock = Clock()
    def slow(i):
        clock.now += 2
        return {}
    out = scan_batch([1, 2], fetch_and_evaluate=slow, save_and_checkpoint=lambda *a: None,
                     clock=clock, sleep=lambda _: pytest.fail('unneeded sleep'))
    assert out['saved'] == 2


@pytest.mark.parametrize('kwargs', [{'max_companies': 0}, {'max_companies': 1001},
                                  {'max_seconds': 0}, {'max_seconds': 1801},
                                  {'min_request_interval': .5}, {'min_request_interval': float('nan')},
                                  {'max_seconds': float('nan')}])
def test_budget_cannot_disable_safety_limits(kwargs):
    with pytest.raises(ValueError):
        ScanBudget(**kwargs)

#!/usr/bin/env python3
"""Synthetic timesheet tests. Run directly with Python 3.9 or newer."""
import contextlib
import csv
import io
import json
import sys
from datetime import date, datetime, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from test_digest import REPO, load
import os

t = load('timesheet', os.path.join(REPO, 'skills', 'timesheet', 'timesheet.py'))
DAY = date(2026, 6, 1)


def event(stamp, project='Web', ident=None):
    return {'ts': int(datetime.fromisoformat(stamp).timestamp() * 1000), 'project': project,
            '_id': ident or stamp + project, 'sessionId': 'synthetic', 'message': 'Build a page.'}


def estimate(rows, **kw):
    return t.estimate(rows, {}, DAY, date(2026, 6, 7), timezone.utc, **kw)


def test_single_block_and_rounding():
    rows = [event('2026-06-01T10:00:00+00:00'), event('2026-06-01T10:20:00+00:00')]
    got = estimate(rows)
    assert got['estimated_total_hours'] == .5 and got['interval_count'] == 2
    assert estimate(rows, rounding=1)['total_minutes_by_day']['2026-06-01'] == 25
    assert got['projects'][0]['unrounded_minutes_by_day']['2026-06-01'] == 25


def test_idle_gap_and_project_switches():
    rows = [event('2026-06-01T10:00:00+00:00'), event('2026-06-01T11:00:00+00:00')]
    assert estimate(rows, rounding=1)['total_minutes_by_day']['2026-06-01'] == 10
    rows = [event('2026-06-01T10:00:00+00:00', 'A'), event('2026-06-01T10:20:00+00:00', 'B')]
    got = estimate(rows, rounding=1)
    assert [p['minutes_by_day']['2026-06-01'] for p in got['projects']] == [5, 20]


def test_midnight_clipping_and_duplicates():
    rows = [event('2026-06-01T23:55:00+00:00'), event('2026-06-02T00:10:00+00:00')]
    got = estimate(rows + rows, rounding=1)
    assert got['event_count'] == 2
    assert list(got['total_minutes_by_day'].values())[:2] == [10, 10]
    assert estimate([event('2026-06-01T00:02:00+00:00')], rounding=1)['estimated_total_hours'] == round(2/60, 4)
    assert estimate([event('2026-06-08T00:00:00+00:00')])['event_count'] == 0


def test_dst_elapsed_time():
    try:
        zone = ZoneInfo('America/New_York')
    except ZoneInfoNotFoundError:
        print('SKIP DST: timezone database unavailable')
        return
    for day, first, last in [('2026-03-08','2026-03-08T01:50:00-05:00','2026-03-08T03:10:00-04:00'),
                              ('2026-11-01','2026-11-01T01:50:00-04:00','2026-11-01T01:10:00-05:00')]:
        d = date.fromisoformat(day)
        got = t.estimate([event(first), event(last)], {}, d, d, zone, rounding=1)
        assert got['total_minutes_by_day'][day] == 25, got


def test_labels_probes_and_empty_week():
    row = event('2026-06-01T10:00:00+00:00', 'raw')
    got = t.estimate([row], {'mappings': {'raw': 'Café'}}, DAY, DAY, timezone.utc)
    assert got['projects'][0]['project'] == 'Café'
    row.update(sessionId='install-verify', project='pulse-install')
    assert estimate([row])['event_count'] == 0
    empty = estimate([])
    assert empty['estimated_total_hours'] == 0 and len(empty['dates']) == 7


def test_period_and_invalid_input():
    assert t.period(None, None, date(2026,6,7)) == (date(2026,5,25), date(2026,5,31))
    assert t.period(None, None, date(2026,6,8)) == (DAY, date(2026,6,7))
    for args in [('2026-06-01',None), ('bad','2026-06-02'), ('2026-06-02','2026-06-01')]:
        try:
            t.period(*args, today=DAY)
            assert False, args
        except ValueError:
            pass
    for kw in [{'idle_gap':0}, {'rounding':0}, {'lead_in':-1}, {'lead_in':31}]:
        try:
            estimate([], **kw)
            assert False, kw
        except ValueError:
            pass
    for stamp in [None, True, float('nan'), float('inf'), '123']:
        try:
            estimate([{'ts':stamp}])
            assert False, stamp
        except ValueError:
            pass


def test_chunked_http_and_malformed_response():
    calls = []
    class Response(io.BytesIO):
        pass
    def opener(req, timeout):
        calls.append(parse_qs(urlparse(req.full_url).query))
        assert req.get_header('Authorization') == 'Bearer synthetic'
        return Response(b'{"rows": []}')
    with patch.object(t, 'urlopen', opener):
        assert t.fetch_events('https://example.invalid', 'synthetic', 0, t.MAX_RANGE_MS * 2 + 1) == []
    assert len(calls) == 3
    assert calls[1]['startTs'] == calls[0]['endTs']
    assert calls[2]['endTs'] == [str(t.MAX_RANGE_MS * 2 + 1)]
    with patch.object(t, 'urlopen', lambda *a, **kw: Response(b'{"error":"bad"}')):
        try:
            t.fetch_events('https://example.invalid', 'synthetic', 0, 1)
            assert False
        except ValueError:
            pass


def test_formats_and_cli_refusal_before_network():
    data = estimate([event('2026-06-01T10:00:00+00:00', '=SUM(A1)')], rounding=1)
    assert json.loads(t.render(data, 'json'))['estimated'] is True
    assert 'Estimated hours' in t.render(data, 'markdown')
    rows = list(csv.reader(io.StringIO(t.render(data, 'csv'))))
    assert rows[1][0].startswith("'=") and 'estimated' in rows[0][0]
    with patch.object(t, 'utf8_stdio'), patch.object(t, 'load_config', return_value={}), \
         patch.object(t, 'fetch_events', side_effect=AssertionError('network called')), \
         patch.object(sys, 'argv', ['timesheet', '--rounding', '0']), \
         contextlib.redirect_stderr(io.StringIO()) as err:
        assert t.main() == 2 and 'rounding' in json.loads(err.getvalue())['error']


def test_interleaved_projects_and_zero_rounding():
    rows = [event('2026-06-01T10:00:00+00:00', 'A'),
            event('2026-06-01T10:01:00+00:00', 'B'),
            event('2026-06-01T10:02:00+00:00', 'A')]
    got = estimate(rows)
    assert [p['unrounded_minutes_by_day']['2026-06-01'] for p in got['projects']] == [6, 1]
    assert got['estimated_total_hours'] == 0
    assert len(list(csv.reader(io.StringIO(t.render(got, 'csv'))))) == 2


if __name__ == '__main__':
    tests = [v for k,v in sorted(globals().items()) if k.startswith('test_')]
    for fn in tests:
        fn()
        print('OK', fn.__name__)
    print(f'\n{len(tests)} passed')

#!/usr/bin/env python3
"""Estimate captured Claude Code hours by project, using turn completion times.

Prints JSON, Markdown or CSV. No LLM, file writes or processed-state changes.
Defaults to the last completed Monday-Sunday week in the configured timezone.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from urllib.error import HTTPError
from urllib.request import urlopen

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared"))
from common import (cfg_get, clean_label, convex_creds, fetch_convex_range, get_tz,
                    is_install_probe, load_config, load_labels, normalize, pulse_home,
                    resolve_labels, utf8_stdio)

NOTICE = "Estimated hours of captured Claude Code activity, not tracked or billable time."
MAX_RANGE_MS = 24 * 60 * 60 * 1000


def period(since, until, today):
    if (since is None) != (until is None):
        raise ValueError("provide both --since and --until")
    if since is None:
        end = today - timedelta(days=today.weekday() + 1)
        return end - timedelta(days=6), end
    try:
        if not all(re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", x) for x in (since, until)):
            raise ValueError()
        start, end = date.fromisoformat(since), date.fromisoformat(until)
    except ValueError:
        raise ValueError("--since and --until must be real YYYY-MM-DD dates") from None
    if start > end or end == date.max:
        raise ValueError("--until must be on or after --since and before 9999-12-31")
    return start, end


def bounds(start, end, tz):
    return (int(datetime.combine(start, time.min, tzinfo=tz).timestamp() * 1000),
            int(datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz).timestamp() * 1000))


def fetch_events(url, token, start_ms, end_ms):
    rows = []
    while start_ms < end_ms:
        stop = min(start_ms + MAX_RANGE_MS, end_ms)
        data = fetch_convex_range(url, token, start_ms, stop, urlopen)
        chunk = data.get("rows") if isinstance(data, dict) else data
        if not isinstance(chunk, list) or not all(isinstance(row, dict) for row in chunk):
            raise ValueError("Convex /all did not return an array of event rows")
        rows.extend(chunk)
        start_ms = stop
    return rows


def estimate(rows, labels, start, end, tz, idle_gap=30, rounding=15, lead_in=5):
    for name, value, minimum in (("idle-gap", idle_gap, 1), ("rounding", rounding, 1), ("lead-in", lead_in, 0)):
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise ValueError(f"--{name} must be an integer of at least {minimum} minutes")
    if lead_in > idle_gap:
        raise ValueError("--lead-in cannot exceed --idle-gap")
    start_ms, end_ms = bounds(start, end, tz)
    seen, events = set(), []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("an event must be an object")
        stamp = row.get("ts")
        if isinstance(stamp, bool) or not isinstance(stamp, (int, float)) or not math.isfinite(stamp):
            raise ValueError("an event has no finite numeric ts timestamp")
        if not start_ms <= stamp < end_ms:
            continue
        event = normalize(row)
        if is_install_probe(event):
            continue
        key = row.get("eventId") or event["id"] or (stamp, event["session"], event["project"], event["cwd"])
        if key in seen:
            continue
        seen.add(key)
        event["ts"] = int(stamp)
        events.append(event)
    events.sort(key=lambda e: (e["ts"], e["id"], e["session"], e["project"]))
    projects = [clean_label(label) for label in resolve_labels(events, labels)]
    blocks = []
    previous = None
    for event, project in zip(events, projects):
        stamp = event["ts"]
        left = previous if previous is not None and stamp - previous <= idle_gap * 60000 else stamp - lead_in * 60000
        blocks.append([project, max(start_ms, left), stamp])
        previous = stamp
    raw = defaultdict(lambda: defaultdict(int))
    for project, left, right in blocks:
        raw[project]
        while left < right:
            local_day = datetime.fromtimestamp(left / 1000, tz).date()
            midnight = int(datetime.combine(local_day + timedelta(days=1), time.min, tzinfo=tz).timestamp() * 1000)
            stop = min(right, midnight)
            if stop <= left:
                raise ValueError("timezone produced a non-increasing day boundary")
            raw[project][local_day.isoformat()] += stop - left
            left = stop
    dates = [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
    quantum = rounding * 60000
    output = []
    for project in sorted(raw):
        minutes = {day: ((2 * raw[project][day] + quantum) // (2 * quantum)) * rounding for day in dates}
        output.append({"project": project, "minutes_by_day": minutes,
                       "unrounded_minutes_by_day": {day: raw[project][day] / 60000 for day in dates},
                       "estimated_hours": round(sum(minutes.values()) / 60, 4)})
    totals = {day: sum(p["minutes_by_day"][day] for p in output) for day in dates}
    return {"estimated": True, "notice": NOTICE, "since": start.isoformat(), "until": end.isoformat(),
            "timezone": str(tz), "idle_gap_minutes": idle_gap, "rounding_minutes": rounding,
            "lead_in_minutes": lead_in, "event_count": len(events), "interval_count": len(blocks),
            "dates": dates, "projects": output, "total_minutes_by_day": totals,
            "estimated_total_hours": round(sum(totals.values()) / 60, 4)}


def render(data, fmt):
    if fmt == "json":
        return json.dumps(data, ensure_ascii=False)
    header = ["Project (estimated Claude Code hours)", *data["dates"], "Estimated total hours"]
    rows = [[p["project"], *[f'{p["minutes_by_day"][d] / 60:.2f}' for d in data["dates"]],
             f'{sum(p["minutes_by_day"].values()) / 60:.2f}'] for p in data["projects"] if any(p["minutes_by_day"].values())]
    rows.append(["Total", *[f'{data["total_minutes_by_day"][d] / 60:.2f}' for d in data["dates"]],
                 f'{sum(data["total_minutes_by_day"].values()) / 60:.2f}'])
    if fmt == "csv":
        out = io.StringIO(newline="")
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow(header)
        for row in rows:
            label = row[0]
            writer.writerow(["'" + label if label.startswith(("=", "+", "-", "@", "\t", "\r")) else label, *row[1:]])
        return out.getvalue().rstrip("\n")
    def line(row):
        return "| " + " | ".join(str(cell).replace("|", "\\|").replace("\n", " ") for cell in row) + " |"
    settings = (f'Idle gap: {data["idle_gap_minutes"]} min; lead-in: {data["lead_in_minutes"]} min; '
                f'rounding: nearest {data["rounding_minutes"]} min per project/day; timezone: {data["timezone"]}.')
    return "\n\n".join([NOTICE, settings, "\n".join([line(header), line(["---"] * len(header)), *map(line, rows)])])


def main():
    utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since")
    parser.add_argument("--until")
    parser.add_argument("--idle-gap", type=int, default=30, help="minutes between turns before a new block")
    parser.add_argument("--rounding", type=int, default=15, help="round project/day totals to this many minutes")
    parser.add_argument("--lead-in", type=int, default=5, help="minutes before the first turn in a block")
    parser.add_argument("--format", choices=("json", "markdown", "csv"), default="markdown")
    args = parser.parse_args()
    cfg = load_config()
    tz = get_tz(cfg)
    try:
        start, end = period(args.since, args.until, datetime.now(tz).date())
        estimate([], {}, start, end, tz, args.idle_gap, args.rounding, args.lead_in)
        url, token, error = convex_creds()
        if error:
            raise ValueError(error)
        labels = load_labels(os.path.expanduser(cfg_get(cfg, "project_labels", None, os.path.join(pulse_home(), "project-labels.yaml"))))
    except (ValueError, OverflowError, OSError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 2
    try:
        rows = fetch_events(url, token, *bounds(start, end, tz))
        result = estimate(rows, labels, start, end, tz, args.idle_gap, args.rounding, args.lead_in)
    except HTTPError as error:
        print(json.dumps({"error": f"fetch failed: HTTP {error.code}"}), file=sys.stderr)
        return 1
    except Exception as error:
        print(json.dumps({"error": f"could not build timesheet ({type(error).__name__}); check the deployment and event data"}), file=sys.stderr)
        return 1
    print(render(result, args.format))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

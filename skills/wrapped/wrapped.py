#!/usr/bin/env python3
"""Count recorded activity for a Pulse month or year and print JSON.

No network calls or file writes. Run with --month YYYY-MM or --year YYYY;
the default is the previous completed month in the configured timezone.
"""
from __future__ import annotations

import argparse
import calendar
import json
import os
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared"))
from common import (LOOP_TAG_RE, TASK_RE, cfg_get, get_tz, h2_body, list_dated_notes,
                    load_config, loop_text, notes_repo_dir, parse_note, read_note,
                    strip_code_blocks, utf8_stdio)

KINDS = ("Outcome", "Decided", "Bug", "Rule", "Learned")
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def resolve_period(month, year, today):
    if month is not None and year is not None:
        raise ValueError("choose --month or --year, not both")
    if year is not None:
        if not re.fullmatch(r"[0-9]{4}", year) or not 1 <= int(year) <= 9999:
            raise ValueError("--year must be YYYY, from 0001 to 9999")
        return date(int(year), 1, 1), date(int(year), 12, 31), year
    if month is None:
        previous = today.replace(day=1) - timedelta(days=1)
        month = f"{previous.year:04d}-{previous.month:02d}"
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", month):
        raise ValueError("--month must be YYYY-MM")
    try:
        start = date.fromisoformat(month + "-01")
    except ValueError:
        raise ValueError("--month must be a real YYYY-MM") from None
    return start, start.replace(day=calendar.monthrange(start.year, start.month)[1]), month


def longest_streak(days):
    longest = current = 0
    previous = None
    for day in sorted(days):
        current = current + 1 if previous and (day - previous).days == 1 else 1
        longest = max(longest, current)
        previous = day
    return longest


def busiest(counts):
    peak = max(counts.values(), default=0)
    return [key for key, value in counts.items() if value == peak] if peak else []


def collect(cfg, month=None, year=None, today=None):
    today = today or datetime.now(get_tz(cfg)).date()
    start, end, period = resolve_period(month, year, today)
    repo = notes_repo_dir(cfg)
    if not repo or not os.path.isdir(repo):
        raise ValueError("no notes repo; run skills/setup/install.py notes")
    daily = cfg_get(cfg, "vault_subfolder", "PULSE_VAULT_SUBFOLDER", "Pulse/Daily")
    folder = cfg_get(cfg, "wrapped_subfolder", "PULSE_WRAPPED_SUBFOLDER", "Pulse/Wrapped")
    target = os.path.realpath(os.path.join(repo, folder, period + ".md"))
    if os.path.commonpath([os.path.realpath(repo), target]) != os.path.realpath(repo):
        raise ValueError("wrapped_subfolder must stay inside the notes repo")

    sources, candidates, transitions = [], [], []
    days, projects, loop_states = set(), {}, {}
    typed = dict.fromkeys(KINDS, 0)
    loop_counts = dict.fromkeys(("first_seen_open", "first_seen_closed", "closed_after_open", "reopened"), 0)
    for path in list_dated_notes(os.path.join(repo, daily)):
        try:
            day = date.fromisoformat(os.path.basename(path)[:-3])
        except ValueError:
            continue
        if not start <= day <= end or os.path.basename(os.path.dirname(path)) != day.isoformat()[:7]:
            continue
        text = strip_code_blocks(read_note(path))
        rel = os.path.relpath(path, repo).replace("\\", "/")
        source = {"date": day.isoformat(), "note": rel, "citation": f"[[{rel[:-3]}|{day.isoformat()}]]"}
        sources.append(source)
        _, blocks = parse_note(text)
        for block in blocks:
            if not block["bullets"]:
                continue
            label = block["project"]
            days.add(day)
            projects.setdefault(label, set()).add(day)
            for bullet in block["bullets"]:
                kind, sep, content = bullet.partition(":")
                if sep and kind in typed and content.strip():
                    typed[kind] += 1
                    if kind == "Outcome":
                        candidates.append({**source, "project": label, "text": content.strip()})
        for line in (h2_body(text, "## Open loops") or "").splitlines():
            task = TASK_RE.match(line)
            if not task:
                continue
            tag = LOOP_TAG_RE.search(task.group(2))
            project = tag.group("project").strip() if tag else None
            since = tag.group("since") if tag else None
            item = loop_text(line)
            key = (project, item, since)
            closed = task.group(1).lower() == "x"
            previous = loop_states.get(key)
            event = None
            if previous is None:
                event = "first_seen_closed" if closed else "first_seen_open"
            elif previous != closed:
                event = "closed_after_open" if closed else "reopened"
            loop_states[key] = closed
            if event:
                loop_counts[event] += 1
                transitions.append({**source, "project": project, "text": item, "since": since, "event": event})

    month_counts = Counter(day.isoformat()[:7] for day in days)
    weekday_counts = Counter(day.weekday() for day in days)
    by_month = {f"{start.year:04d}-{m:02d}": month_counts[f"{start.year:04d}-{m:02d}"]
                for m in range(start.month, end.month + 1)}
    by_weekday = {name: weekday_counts[i] for i, name in enumerate(WEEKDAYS)}
    return {
        "period": period, "since": start.isoformat(), "until": end.isoformat(),
        "notes_repo_dir": repo, "wrapped_note_path": target,
        "notes_scanned": len(sources), "sources": sources,
        "recorded_work_days": len(days), "longest_streak_days": longest_streak(days),
        "projects": [{"project": name, "day_count": len(dates), "days": sorted(d.isoformat() for d in dates)}
                     for name, dates in sorted(projects.items(), key=lambda pair: (-len(pair[1]), pair[0]))],
        "days_by_month": by_month, "busiest_months": busiest(by_month),
        "days_by_weekday": by_weekday, "busiest_weekdays": busiest(by_weekday),
        "typed_bullets": typed, "outcome_candidates": candidates,
        "loops": {**loop_counts, "last_seen_open": sum(not closed for closed in loop_states.values()),
                  "observations": transitions},
    }


def main():
    utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--month", help="YYYY-MM, default the previous completed month")
    group.add_argument("--year", help="YYYY, inclusive calendar year")
    args = parser.parse_args()
    try:
        result = collect(load_config(), args.month, args.year)
    except (ValueError, OSError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

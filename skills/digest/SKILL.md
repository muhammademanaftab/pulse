---
name: digest
description: Turn a day of captured Claude Code sessions into a readable Obsidian daily note in the user's notes repo. Use when the user asks to digest a day, build the daily note, or catch up the daily memory. Also run unattended by the nightly digest routine.
disable-model-invocation: true
argument-hint: "[date: YYYY-MM-DD | yesterday | today, default yesterday]"
---

# Digest (L3): captured rows to an Obsidian daily note

Turn one day's captured rows (from the user's Convex deployment) into an
Obsidian-style daily note in the user's notes git repo. The note is fully derived
from the event log, so this regenerates and overwrites it each run. The raw rows
are the source of truth and are never edited here.

This skill writes the note, runs the gates, and has a reviewer subagent verify it
before anything is pushed. It reports the row ids back; the caller (the digest
routine, or a manual run) is what commits, pushes, and marks the rows processed.
**Never mark rows processed until the note is confirmed pushed.**

Run the commands below from the repo root (the digest routine clones the repo and
runs from there); paths like `skills/digest/digest.py` are relative to it.

## Steps

1. **Resolve the date.** Use the argument if given (`YYYY-MM-DD`, `yesterday`, or
   `today`), else `yesterday`.

2. **Get the prepared buckets** (fetches the day's rows from Convex via
   `~/.pulse/.env`, dedups, applies the optional label map, buckets by project,
   drops trivial noise):

   ```bash
   python3 skills/digest/digest.py fetch --date <date> > /tmp/pulse-digest.json
   ```

   The JSON has: `date, timezone, notes_repo_dir, vault_subfolder, projects_dir,
   hub_prefix, index_name, note_path, event_count, project_count, buckets:[{project,
   events:[{ts,prompt,response,id}]}], row_ids`. Use `note_path`, `projects_dir`,
   `hub_prefix`, and `index_name` from here; do not hand-build paths.

3. **Quiet day.** If `event_count` is 0, do nothing: write no note, make no commit,
   mark nothing. Report "no captured sessions for <date>" and stop.

4. **Read the rules once** before writing any bullet:
   - `references/bullet-quality.md` (truth-check against the response, exact
     names/counts, don't bullet plumbing)
   - `references/signals.md` (capture decisions, briefs, confusion→resolution,
     failures-with-lessons)
   - `references/humanizer.md` (the AI-writing tells to avoid; applied in step 5b).
     This is the only tone guide: plain English, no AI vocabulary, no em dashes.

5. **Write the note at `note_path`** from the JSON, using this skill's
   `templates/daily-note.md`
   (create the month folder if needed). Fill `<DATE>` and `<DAY_HEADER>`
   (`Weekday, Month D, YYYY`). Sections:
   - **Summary**: 1 to 2 sentences naming the day's biggest outcomes.
   - **Work log**: one block per bucket, in the JSON's order. Get each block's
     heading from `digest.py render-block` so the project label is linked correctly
     (a project becomes `### [[Project]]` only if its note exists in `projects_dir`,
     else `### **Project**`); never hand-type a `[[wikilink]]`:

     ```bash
     printf '%s' "<your bullets>" | python3 skills/digest/digest.py render-block \
       --project "<project>" --projects-dir "<projects_dir>"
     ```

     Write 2 to 6 outcome-focused bullets per project per bullet-quality.md. Verify
     each bullet against the event `response` and its tool calls, not the prompt.
   - **Decisions & signals**: pull signals across all buckets per signals.md. Omit
     the heading if there are none.
   - **Next**: 1 to 3 concrete open threads. Never list work the log shows finished.
     Omit the heading if there are none.

5b. **Humanizer pass (readability, required).** Before saving, apply the
   `references/humanizer.md` checklist to every line you wrote (Summary, Work log,
   Decisions & signals, Next). It is a checklist, not a script: rewrite in place so
   the note reads like a person wrote it. Strip the tells it lists (em dashes, AI
   vocabulary, rule-of-three filler, negative parallelisms, `-ing` pseudo-analysis,
   inline-header lists, vague attributions). Locally you may invoke the `humanizer`
   Skill directly; the vendored copy is the fallback for cloud routines where
   `~/.claude/skills/` is absent. **Hard constraints, never break them:** keep every
   real file name, path, count, and ID exactly (rewrite phrasing only, never drop or
   invent a fact); keep bullets terse; do NOT add personality, opinions, or first
   person (a work log is technical text, so neutral and plain is the correct human
   voice).

6. **Overwrite** any existing note for the date. Do not append.

7. **Wire the Obsidian graph.** Link the note into its month hub and the index
   (idempotent, creates them if missing):

   ```bash
   python3 skills/digest/digest.py month-links \
     --vault "<notes_repo_dir>" --subfolder "<vault_subfolder>" --date <date> \
     --hub-prefix "<hub_prefix>" --index "<index_name>"
   ```

8. **Run the gates in order. Any failure stops the run: do not commit, push, or
   mark rows processed.** Fix the note and re-run the failed gate.
   - Lint: `python3 skills/digest/digest.py lint "<note_path>"`
   - Coverage: `python3 skills/digest/digest.py coverage --digest-json /tmp/pulse-digest.json --note "<note_path>" --projects-dir "<projects_dir>"`
   - Link health: `python3 skills/digest/digest.py check-links --vault "<notes_repo_dir>" --subfolder "<vault_subfolder first segment>"`

8b. **Reviewer subagent (fidelity check, required before push).** The gates in
   step 8 check the note's *form*; they cannot tell whether the bullets are *true*.
   Dispatch a fresh subagent with the Agent tool to check that. Give it exactly:
   - the note you wrote (read `note_path` and paste its full contents), and
   - the digest JSON `/tmp/pulse-digest.json` (the raw `buckets` with each event's
     `prompt` and `response`).

   Tell the subagent its job is to return `PASS`, or `FAIL` with the exact gaps,
   judging only against the raw rows (it must not invent or assume):
   - **Coverage of substance**: every project that has events in the JSON is
     represented in the note, and the real work behind it is captured (not just the
     project named with a hollow bullet).
   - **Fidelity**: each bullet reflects what the `response` and its `tool_use` calls
     actually show. Flag any invented work, any wrong verb (e.g. "merged" when only a
     delete ran), and any claim not supported by the rows.
   - **Biggest win present**: the day's most important outcome (a passed test, a
     shipped artifact, a live result) appears, not only setup steps.
   - **No false "nothing left" claims**: if a thread was dropped, it is acknowledged.

   If the reviewer returns FAIL, fix the note for the exact gaps it named, then
   re-run step 8 (the gates) and re-review. Only proceed to step 9 on PASS. Do not
   push or mark a note the reviewer has not passed.

9. **Commit, push, mark.** In the notes repo: commit the note, push to its branch,
   then verify the push landed (`HEAD` equals `origin/<branch>`). Only after that,
   `POST {CONVEX_URL}/mark-processed` with `{"ids": row_ids}`. If the push fails or
   the SHAs differ, stop and do not mark: the rows stay unprocessed and the next run
   regenerates the same note and retries.

## Rules

- The daily note is derived: always safe to regenerate from the rows.
- Truth lives in the `response`, never claim what you cannot verify there.
- Plain English, no em dashes, no AI vocabulary (the humanizer pass enforces this).
- Every note ships through the humanizer pass (step 5b). A note that reads like AI
  output (em dashes, rule-of-three, AI vocabulary, inline-header lists) is a failed
  note, even if every fact is correct.
- Never hand-type a `[[wikilink]]`. Headings come from `digest.py render-block`;
  graph links come from `digest.py month-links`. This is what keeps the graph free
  of dead links and orphans.
- Never edit the raw rows. This skill only reads them (via the script) and writes
  under the notes repo.
- The mechanical gates (step 8) check form; the reviewer subagent (step 8b) checks
  truth. Both must pass before pushing. Never skip the reviewer on an unattended run.
- Never mark a row processed until its note is confirmed pushed.

$ARGUMENTS

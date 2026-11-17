# Contributing to Pulse

Thanks for helping. Pulse is small on purpose, so most changes are a few lines plus a
test. This page covers how to find something to work on, how to run the tests, and the
house rules a PR is reviewed against. Everyone taking part is expected to follow the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Find something to work on

- Issues labeled [good first issue](https://github.com/muhammademanaftab/pulse/labels/good%20first%20issue)
  are scoped to one file and come with a hint on where to start.
- Issues labeled [help wanted](https://github.com/muhammademanaftab/pulse/labels/help%20wanted)
  are bigger, often a new skill.
- Comment on an issue before you start so two people do not build the same thing.
- For a new idea, open an issue or a discussion first, so we can agree on the shape
  before you write code.

## Set up

There is nothing to install for development. The scripts use only the Python standard
library and must run on Python 3.9 (the macOS system `python3`).

```
git clone https://github.com/<you>/pulse.git
cd pulse
git checkout develop
```

You do not need a Convex account or a notes repo to work on the scripts or run the
tests. You only need them to try a real capture or a real nightly note.

## Run the tests

Each test file runs on its own with `python3`, no test runner needed:

```
for f in tests/test_*.py; do python3 "$f" || break; done
```

CI runs the same files on Linux and Windows, on Python 3.9 and 3.12, so avoid
POSIX-only assumptions (open text files with `encoding="utf-8"`, build paths with
`os.path` or `pathlib`).

## Branches and pull requests

- `main` is what users install. `develop` is where work lands. **Open your PR against
  `develop`.**
- Releases are tagged from `main` (for example `v0.3.0`), and the cloud routines clone
  a pinned tag, so nothing reaches unattended runs until it is released.
- One change per PR. A bug fix and a refactor are two PRs.
- Commit messages follow the style already in the log: `fix: ...`, `feat: ...`,
  `docs: ...`, `ci: ...`, `test: ...`.
- Link the issue in the PR description (`Closes #28`).

## House rules

PRs are reviewed against these, so checking them first saves a round trip:

- **Standard library only**, Python 3.9 compatible.
- **No code comments.** Docstrings that double as CLI help are fine. Name things so the
  code reads without them.
- **No em dashes**, anywhere: code, docs, commit messages. Use commas, periods, colons
  or parentheses.
- **Plain English** in docs and output, no hype words.
- **Few files.** One script per skill. Code that two skills share goes in
  `skills/shared/common.py`, never copied.
- **A new skill** is one folder under `skills/` with a `SKILL.md` and one script that
  imports `common`, plus `tests/test_<skill>.py` and a step for it in
  `.github/workflows/ci.yml`.
- **Tests come with the change.** For a bug, add a test that fails before the fix.

## Privacy

Pulse handles people's private sessions, so test data must be made up.

- Never commit captured data, `.env` files, `*.jsonl`, or real notes.
- For secrets in tests, build fake values in code (for example `"npm_" + "a1B2" * 9`)
  instead of pasting anything that looks like a real key.
- Security problems go through a private advisory, not an issue. See
  [SECURITY.md](SECURITY.md).

## AI-assisted PRs

Welcome. Say in the PR description that an AI tool helped, and run the tests yourself
before opening it. You are responsible for the change either way.

## License

By contributing you agree that your work is released under the [MIT License](LICENSE).

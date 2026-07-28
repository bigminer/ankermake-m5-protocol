#!/usr/bin/env python3
"""Mechanically check the system of record for contradictions.

Run it like `check-secrets.sh` -- before every stage, commit, or push, and in CI.

Why this exists: the discipline in documentation/INDEX.md was convention, so it
survived exactly as long as someone remembered it. The 2026-07-27 audit found the
same refuted claim living in four files, and INDEX fact F-007 went stale one
commit after the index was written. A rule nothing checks is a rule that decays.

Four checks, each covering a failure mode this repo actually had:

  1. REFUTED-LEAK   a claim listed as dead in INDEX section 6 reappears in a doc
                    -- or an agent memory note -- with no correction marker near it
  2. VERIFY-ROT     a `verify` command attached to an INDEX fact no longer finds
                    anything -- the fact has drifted from the code
  3. DEAD-LINK      an INDEX link points at a file that does not exist
  4. TIER-3-DRIFT   this repo's code changed but the fact rows describing it were
                    not touched (advisory only; exit code unaffected)

Exit 1 on any failure in checks 1-3. Check 4 warns, because it cannot know
whether the change was relevant.

Scope note: agent memory notes live outside the repo, under
~/.claude/projects/<slug>/memory. They are covered when present, because they are
auto-loaded into every session's context and a stale claim there arrives as
background truth without anyone asking for it. **CI cannot see them**, so memory
coverage is local-only -- run this before committing, not just in the pipeline.
Point ANKERCTL_MEMORY_DIR at another directory to override.
"""
import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = ROOT / "documentation" / "INDEX.md"


def memory_dir():
    """Locate this project's agent memory, without hardcoding a personal path.

    Claude Code stores it at ~/.claude/projects/<abs-repo-path with / as ->/memory.
    Derived, never written down: the literal path contains a home directory and
    committing it would trip the secret sweep. Returns None when absent -- CI has
    no memory directory, and that is not a failure.
    """
    override = os.environ.get("ANKERCTL_MEMORY_DIR")
    if override:
        path = pathlib.Path(override)
        return path if path.is_dir() else None
    slug = str(ROOT).replace("/", "-")
    path = pathlib.Path.home() / ".claude" / "projects" / slug / "memory"
    return path if path.is_dir() else None

# Phrases that were refuted. If one appears without a correction marker nearby,
# it is poisoning whatever reads it. Keep in sync with INDEX section 6.
REFUTED = [
    ("no fan-state fact", "the printer reports 1005 -- INDEX F-003"),
    ("publishes no fan-state", "the printer reports 1005 -- INDEX F-003"),
    ("not honored by production firmware", "G36 ran 10C too cold -- INDEX section 6"),
    ("does not honor `G36`", "G36 ran 10C too cold -- INDEX section 6"),
    ("raw stepper counts", "Count X: is planner.position -- INDEX F-020"),
    ("never been published", "eufyMake-linux-sdk is public -- INDEX section 6"),
    ("no proprioception", "M114 always worked -- INDEX section 6"),
    ("full control parity", "ankerctl lacks parity -- see local-control-research banner"),
]

# Any of these within PROXIMITY lines means the claim is already marked dead.
MARKERS = re.compile(
    r"REFUTED|refuted|~~|⚠️|corrected|Corrected|SUPERSEDED|superseded|"
    r"do not resurrect|was believed|previously read|used to (say|open|read)|"
    # A passage may retire a claim without using the word "refuted".
    r"imprecise|not a supported claim|no longer|is wrong|was wrong|not supported",
)
PROXIMITY = 12

SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", "captures"}
# These files are *about* refuted claims; their job is to quote them.
SKIP_FILES = {"INDEX.md", "audit-2026-07-27.md", "check-docs.py"}


def _docs():
    for path in ROOT.rglob("*.md"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name in SKIP_FILES:
            continue
        yield path
    # Agent memory notes are auto-loaded into every session's context without
    # being asked for, so a refuted claim there is worse than one in a doc: it
    # arrives as background truth. Same rules apply.
    mem = memory_dir()
    if mem:
        yield from sorted(mem.glob("*.md"))


def _label(path):
    """Repo-relative where possible; memory notes are outside the repo."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return f"memory/{path.name}"


def check_refuted_leaks():
    failures = []
    for path in _docs():
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for i, line in enumerate(lines):
            for phrase, why in REFUTED:
                if phrase.lower() not in line.lower():
                    continue
                window = "\n".join(lines[max(0, i - PROXIMITY): i + PROXIMITY])
                if MARKERS.search(window):
                    continue
                failures.append(
                    f"{_label(path)}:{i + 1}: refuted claim "
                    f"{phrase!r} with no correction nearby ({why})"
                )
    return failures


def check_verify_commands():
    """Run each `grep ...` in an INDEX verify column; a no-match means drift."""
    failures = []
    text = INDEX.read_text(encoding="utf-8")
    for row in re.finditer(r"^\|\s*(F-\d+)\s*\|.*\|\s*`([^`]*grep[^`]*)`\s*\|$",
                           text, re.M):
        fact, cmd = row.group(1), row.group(2).replace(r"\|", "|")
        try:
            done = subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True,
                                  text=True, timeout=30)
        except subprocess.TimeoutExpired:
            failures.append(f"INDEX {fact}: verify command timed out: {cmd}")
            continue
        # grep -c legitimately prints 0 for facts asserting absence.
        if done.returncode != 0 and not done.stdout.strip():
            failures.append(
                f"INDEX {fact}: verify command found nothing -- the fact may have "
                f"drifted from the code: {cmd}"
            )
    return failures


def check_links():
    failures = []
    text = INDEX.read_text(encoding="utf-8")
    for link in re.finditer(r"\[[^\]]+\]\(([^)#]+)\)", text):
        target = link.group(1)
        if target.startswith(("http://", "https://")):
            continue
        if not (INDEX.parent / target).exists():
            failures.append(f"INDEX: dead link -> {target}")
    return failures


def check_tier3_drift():
    """Advisory: code touched in this commit without touching its fact rows."""
    try:
        changed = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=ROOT, capture_output=True, text=True, timeout=15,
        ).stdout.split()
    except Exception:
        return []
    if not changed:
        return []
    touched_code = [f for f in changed
                    if f.startswith(("web/", "static/", "libflagship/"))]
    touched_index = any(f.endswith("documentation/INDEX.md") for f in changed)
    if touched_code and not touched_index:
        return [
            "advisory: staged changes touch " + ", ".join(sorted(touched_code)[:4])
            + " but not documentation/INDEX.md. Tier 3 fact rows (F-007, F-008, "
            "F-021, F-022) describe this code -- confirm none went stale. "
            "INDEX section 10."
        ]
    return []


def main():
    hard = []
    for name, fn in (("REFUTED-LEAK", check_refuted_leaks),
                     ("VERIFY-ROT", check_verify_commands),
                     ("DEAD-LINK", check_links)):
        found = fn()
        hard += [f"[{name}] {f}" for f in found]

    advisory = [f"[TIER-3-DRIFT] {f}" for f in check_tier3_drift()]

    for line in advisory:
        print(line)
    if hard:
        print()
        for line in hard:
            print(line)
        print(f"\n✗ {len(hard)} contradiction(s). See documentation/INDEX.md.")
        return 1
    print("✓ System of record consistent — no refuted leaks, no fact drift, "
          "no dead links.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Season-rollover readiness pins (2026-11-02).

docs/SEASON-ROLLOVER.md is the contract: rolling to a new season must be a
data/config exercise, never a code change. These tests pin the code-side
half of that contract so a regression cannot ship silently:

  1. The viewer build-hash week bump is SEASON-PRESERVING — the year on the
     page is kept, only the week segment is rewritten. (The pre-fix regex
     pinned "2026" literally; on a 2027 page it would have silently
     no-opped and the cache-bump convention would have drifted.)
  2. The freeze target resolver derives season/week from FILENAMES, not
     constants — a 2027 games file resolves as season 2027.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_autopilot() -> re.Pattern:
    """Import-free: pull BUILD_HASH_RE's source and behavior from the module
    without executing its network-adjacent module body twice."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("autopilot_under_test", ROOT / "scripts" / "autopilot.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_hash_regex_matches_any_season_and_preserves_it_on_week_bump():
    autopilot = _load_autopilot()
    pattern = autopilot.BUILD_HASH_RE
    for page_hash in ["2026-w7-v15", "2027-w1-v9", "2031-w18-v4"]:
        match = pattern.search(f"build {page_hash}")
        assert match, f"BUILD_HASH_RE no longer matches {page_hash}"
        season, week, version = match.group(1), match.group(2), match.group(3)
        bumped = pattern.sub(lambda m: f"{m.group(1)}-w3-{m.group(3)}", f"build {page_hash}")
        assert bumped == f"build {season}-w3-{version}", f"week bump lost the season for {page_hash}"


def test_bump_build_hash_week_rewrites_only_the_week_segment(tmp_path, monkeypatch):
    autopilot = _load_autopilot()
    page = tmp_path / "index.html"
    page.write_text('<meta name="build-hash" content="2027-w1-v32">\n', encoding="utf-8")
    monkeypatch.setattr(autopilot, "VIEWER", tmp_path)
    monkeypatch.setattr(autopilot, "ROOT", tmp_path)
    changed = autopilot.bump_build_hash_week(2)
    assert changed == ["index.html"]
    assert page.read_text(encoding="utf-8") == '<meta name="build-hash" content="2027-w2-v32">\n'


def test_freeze_resolver_reads_season_from_filename_not_constants():
    resolver_src = (ROOT / "scripts" / "resolve_freeze_target.py").read_text(encoding="utf-8")
    assert 'FILE_RE = re.compile(r"games_(\\d{4})_w(\\d+)\\.json$")' in resolver_src
    # no literal season anywhere in the resolver
    assert not re.search(r'"20\d\d[_-]w?"', resolver_src), "resolver must not hardcode a season"


def test_season_rollover_runbook_exists_and_names_the_fix():
    runbook = (ROOT / "docs" / "SEASON-ROLLOVER.md").read_text(encoding="utf-8")
    assert "BUILD_HASH_RE" in runbook
    assert "2027" in runbook
    assert "nfl.js" in runbook

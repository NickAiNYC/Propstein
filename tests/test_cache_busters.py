"""Cache-buster gate: viewer JS/CSS edits must bump ?v= and CACHE_NAME."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from scripts.check_cache_busters import cache_buster_violations

ROOT = Path(__file__).resolve().parents[1]


def _sw(cache_name: str, assets: list[str]) -> str:
    body = ",\n".join(f"  '{item}'" for item in assets)
    return f"const CACHE_NAME = '{cache_name}';\nconst STATIC_ASSETS = [\n{body}\n];\n"


def test_unbumped_js_change_fails() -> None:
    page = '<script src="/app.js?v=2026_v228"></script>'
    files = {
        "viewer/index.html": page,
        "viewer/audit.html": page,
        "viewer/sw.js": _sw("propstein-v228-refresh-2026", ["/app.js?v=2026_v228"]),
    }
    failed = cache_buster_violations(["viewer/app.js"], files, files)
    text = "\n".join(failed)
    assert "viewer/app.js changed but viewer/index.html still references /app.js?v=2026_v228" in text
    assert "viewer/app.js changed but viewer/audit.html still references /app.js?v=2026_v228" in text
    assert "viewer/app.js changed but viewer/sw.js still references /app.js?v=2026_v228" in text


def test_unbumped_css_change_fails() -> None:
    files = {
        "viewer/index.html": '<link rel="stylesheet" href="/style.css?v=2026_v228">',
        "viewer/sw.js": _sw("propstein-v228-refresh-2026", ["/style.css?v=2026_v228"]),
    }
    failed = cache_buster_violations(["viewer/style.css"], files, files)
    text = "\n".join(failed)
    assert "viewer/style.css changed but viewer/index.html still references /style.css?v=2026_v228" in text
    assert "viewer/style.css changed but viewer/sw.js still references /style.css?v=2026_v228" in text


def test_bumped_change_with_cache_name_passes() -> None:
    # Pre-existing drift on an untouched asset must not fail the gate.
    base = {
        "viewer/index.html": (
            '<script src="/js/today-schedule.js?v=2026_v208"></script>\n'
            '<link rel="stylesheet" href="/style.css?v=2026_v228">'
        ),
        "viewer/audit.html": '<script src="/app.js?v=2026_v226"></script>',
        "viewer/sw.js": _sw(
            "propstein-v227-refresh-2026",
            [
                "/js/today-schedule.js?v=2026_v208",
                "/style.css?v=2026_v228",
                "/app.js?v=2026_v228",
            ],
        ),
    }
    head = {
        "viewer/index.html": (
            '<script src="/js/today-schedule.js?v=2026_v209"></script>\n'
            '<link rel="stylesheet" href="/style.css?v=2026_v228">'
        ),
        "viewer/audit.html": '<script src="/app.js?v=2026_v226"></script>',
        "viewer/sw.js": _sw(
            "propstein-v228-refresh-2026",
            [
                "/js/today-schedule.js?v=2026_v209",
                "/style.css?v=2026_v228",
                "/app.js?v=2026_v228",
            ],
        ),
    }
    assert cache_buster_violations(["viewer/js/today-schedule.js"], base, head) == []


def test_bumped_query_without_cache_name_fails() -> None:
    base = {
        "viewer/index.html": '<script src="/app.js?v=2026_v228"></script>',
        "viewer/sw.js": _sw("propstein-v228-refresh-2026", ["/app.js?v=2026_v228"]),
    }
    head = {
        "viewer/index.html": '<script src="/app.js?v=2026_v229"></script>',
        "viewer/sw.js": _sw("propstein-v228-refresh-2026", ["/app.js?v=2026_v229"]),
    }
    failed = cache_buster_violations(["viewer/app.js"], base, head)
    assert failed
    assert any("CACHE_NAME is unchanged" in item for item in failed)
    assert all("still references" not in item for item in failed)
    assert all("disagree" not in item for item in failed)


def test_sw_html_version_mismatch_fails() -> None:
    base = {
        "viewer/index.html": '<script src="/app.js?v=2026_v228"></script>',
        "viewer/sw.js": _sw("propstein-v228-refresh-2026", ["/app.js?v=2026_v228"]),
    }
    head = {
        "viewer/index.html": '<script src="/app.js?v=2026_v230"></script>',
        "viewer/sw.js": _sw("propstein-v229-refresh-2026", ["/app.js?v=2026_v229"]),
    }
    failed = cache_buster_violations(["viewer/app.js"], base, head)
    text = "\n".join(failed)
    assert "versions disagree between HTML and viewer/sw.js STATIC_ASSETS" in text
    assert "viewer/index.html references /app.js?v=2026_v230" in text
    assert "viewer/sw.js STATIC_ASSETS references /app.js?v=2026_v229" in text
    assert "still references" not in text
    assert "CACHE_NAME" not in text


def test_partial_reference_bump_fails() -> None:
    base = {
        "viewer/index.html": '<script src="/app.js?v=2026_v228"></script>',
        "viewer/audit.html": '<script src="/app.js?v=2026_v226"></script>',
        "viewer/sw.js": _sw("propstein-v228-refresh-2026", ["/app.js?v=2026_v228"]),
    }
    head = {
        "viewer/index.html": '<script src="/app.js?v=2026_v229"></script>',
        "viewer/audit.html": '<script src="/app.js?v=2026_v226"></script>',
        "viewer/sw.js": _sw("propstein-v229-refresh-2026", ["/app.js?v=2026_v229"]),
    }
    failed = cache_buster_violations(["viewer/app.js"], base, head)
    text = "\n".join(failed)
    assert "viewer/audit.html still references /app.js?v=2026_v226" in text
    assert "still references /app.js?v=2026_v228" not in text
    assert "viewer/audit.html references /app.js?v=2026_v226" in text
    assert "viewer/sw.js STATIC_ASSETS references /app.js?v=2026_v229" in text


def test_changes_outside_viewer_pass() -> None:
    files = {
        "viewer/audit.html": '<script src="/app.js?v=2026_v226"></script>',
        "viewer/sw.js": _sw("propstein-v228-refresh-2026", ["/app.js?v=2026_v228"]),
    }
    changed = [
        "src/model.py",
        "data/slate.json",
        "viewer/live_odds_feed.json",
        "viewer/snapshots_2026_w7.json",
        "notes/readme.md",
    ]
    assert cache_buster_violations(changed, files, dict(files)) == []


def test_unreferenced_viewer_asset_passes() -> None:
    files = {
        "viewer/index.html": '<script src="/app.js?v=2026_v228"></script>',
        "viewer/sw.js": _sw("propstein-v228-refresh-2026", ["/app.js?v=2026_v228"]),
    }
    assert cache_buster_violations(["viewer/js/unused-helper.js"], files, files) == []


def test_sw_js_change_without_cache_name_fails() -> None:
    files = {
        "viewer/audit.html": '<script src="/app.js?v=2026_v226"></script>',
        "viewer/sw.js": _sw("propstein-v228-refresh-2026", ["/app.js?v=2026_v228"]),
    }
    failed = cache_buster_violations(["viewer/sw.js"], files, files)
    assert len(failed) == 1
    assert "viewer/sw.js changed but viewer/sw.js CACHE_NAME is unchanged" in failed[0]
    assert "disagree" not in failed[0]


def test_sw_js_cache_name_bump_ignores_preexisting_drift() -> None:
    base = {
        "viewer/audit.html": '<script src="/app.js?v=2026_v226"></script>',
        "viewer/sw.js": _sw("propstein-v228-refresh-2026", ["/app.js?v=2026_v228"]),
    }
    head = {
        "viewer/audit.html": base["viewer/audit.html"],
        "viewer/sw.js": _sw("propstein-v229-refresh-2026", ["/app.js?v=2026_v228"]),
    }
    assert cache_buster_violations(["viewer/sw.js"], base, head) == []


def test_cache_buster_script_passes_on_this_branch() -> None:
    completed = subprocess.run(
        ["python3", "scripts/check_cache_busters.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert "still references" not in completed.stderr
    assert "disagree" not in completed.stderr


def test_cache_buster_fallback_when_base_commit_is_unavailable() -> None:
    env = os.environ.copy()
    env["CACHE_BUSTER_BASE"] = "nonexistent_sha_0123456789"
    env["GIT_TERMINAL_PROMPT"] = "0"
    completed = subprocess.run(
        ["python3", "scripts/check_cache_busters.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    assert (
        "WARNING: Cache-buster base commit 'nonexistent_sha_0123456789' is not available"
        in completed.stderr
    )
    assert "Falling back to" in completed.stderr

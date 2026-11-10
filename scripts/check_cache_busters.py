#!/usr/bin/env python3
"""Fail when a viewer JS/CSS change leaves a stale cache buster.

Production serves viewer/ as a static site. HTML pages and viewer/sw.js load
scripts and stylesheets with ?v= query tags, and the service worker precaches
those exact URLs under CACHE_NAME. For every changed viewer/**/*.js or
viewer/**/*.css file that is referenced with a ?v= tag (viewer/sw.js itself
excluded): every such reference must use a new ?v= value, CACHE_NAME must
change, and the ?v= values in viewer/sw.js STATIC_ASSETS must match the HTML
references. A change to viewer/sw.js itself only requires a CACHE_NAME bump.
Data JSON files are out of scope.

The diff base is CACHE_BUSTER_BASE (a commit). When that commit is missing
locally and from origin, resolution falls back the same way the size gate does.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SW_PATH = "viewer/sw.js"

_ASSET_REF_RE = re.compile(
    r"(?:https?://(?P<host>[^/\s]+))?"
    r"(?P<path>/(?:[A-Za-z0-9_.~-]+/)*[A-Za-z0-9_.~-]+\.(?:js|css))"
    r"\?v=(?P<version>[A-Za-z0-9_.-]+)"
)
_CACHE_NAME_RE = re.compile(
    r"""\bCACHE_NAME\s*=\s*(?P<quote>['"])(?P<value>.*?)(?P=quote)"""
)
_STATIC_ASSETS_RE = re.compile(
    r"\bSTATIC_ASSETS\s*=\s*\[(?P<body>.*?)\]\s*;",
    re.DOTALL,
)
_ALLOWED_HOSTS = frozenset({"propstein.com", "www.propstein.com"})


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, stderr=subprocess.PIPE)


def verify_commit(ref: str) -> bool:
    try:
        _git("rev-parse", "--verify", f"{ref}^{{commit}}")
        return True
    except subprocess.CalledProcessError:
        return False


def try_fetch(ref: str) -> bool:
    try:
        subprocess.check_output(
            ["git", "fetch", "origin", ref, "--depth=2"],
            cwd=ROOT,
            stderr=subprocess.PIPE,
        )
        return verify_commit(ref)
    except subprocess.CalledProcessError:
        return False


def get_merge_base(target: str = "origin/main", head: str = "HEAD") -> str | None:
    try:
        out = _git("merge-base", target, head).strip()
        if out:
            return out
    except subprocess.CalledProcessError:
        pass

    try:
        subprocess.check_output(
            ["git", "fetch", "origin", "+refs/heads/main:refs/remotes/origin/main", "--depth=2"],
            cwd=ROOT,
            stderr=subprocess.PIPE,
        )
        out = _git("merge-base", target, head).strip()
        if out:
            return out
    except subprocess.CalledProcessError:
        pass
    return None


def resolve_base() -> str | None:
    raw_base = os.environ.get("CACHE_BUSTER_BASE", "").strip()
    if raw_base and set(raw_base) != {"0"}:
        if verify_commit(raw_base):
            return raw_base
        if try_fetch(raw_base):
            return raw_base

        fallback = get_merge_base("origin/main", "HEAD")
        if not fallback:
            if verify_commit("HEAD~1"):
                fallback = "HEAD~1"
            else:
                try:
                    subprocess.check_output(
                        ["git", "fetch", "--deepen=1"],
                        cwd=ROOT,
                        stderr=subprocess.PIPE,
                    )
                    if verify_commit("HEAD~1"):
                        fallback = "HEAD~1"
                except subprocess.CalledProcessError:
                    pass

        if fallback:
            print(
                f"WARNING: Cache-buster base commit '{raw_base}' is not available in local tree or remote. "
                f"Falling back to {fallback}.",
                file=sys.stderr,
            )
            return fallback

        print(
            f"WARNING: Cache-buster base commit '{raw_base}' is not available and no fallback commit could be resolved.",
            file=sys.stderr,
        )
        return raw_base

    fallback = get_merge_base("origin/main", "HEAD")
    if fallback:
        try:
            head = _git("rev-parse", "HEAD").strip()
            if fallback == head:
                return None
            return fallback
        except subprocess.CalledProcessError:
            return fallback

    if verify_commit("origin/main"):
        try:
            head = _git("rev-parse", "HEAD").strip()
            main = _git("rev-parse", "origin/main").strip()
            if head == main:
                return None
            return "origin/main"
        except subprocess.CalledProcessError:
            pass

    return None


def changed_paths(base: str) -> list[str]:
    out = _git("diff", "--name-status", "--find-renames", base, "HEAD")
    paths: list[str] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0]
        if status.startswith(("R", "C")):
            paths.extend(parts[1:])
        else:
            paths.append(parts[-1])
    return paths


def is_viewer_code_asset(path: str) -> bool:
    """True for viewer JS/CSS other than the service worker itself."""
    norm = path.replace("\\", "/").strip()
    if norm == SW_PATH or not norm.startswith("viewer/") or norm.endswith("/"):
        return False
    return norm.endswith(".js") or norm.endswith(".css")


def is_reference_source(path: str) -> bool:
    norm = path.replace("\\", "/").strip()
    if norm == SW_PATH:
        return True
    return norm.startswith("viewer/") and norm.endswith(".html")


def _asset_from_url_path(url_path: str) -> str | None:
    if not url_path.startswith("/"):
        return None
    parts = [part for part in url_path.split("/") if part]
    if not parts or any(part == ".." for part in parts):
        return None
    return "viewer/" + "/".join(parts)


def extract_versioned_refs(text: str) -> list[tuple[str, str, str]]:
    """Return (repo asset path, URL path, version) for ?v= JS/CSS references."""
    if not text:
        return []
    found: list[tuple[str, str, str]] = []
    for match in _ASSET_REF_RE.finditer(text):
        host = match.group("host")
        if host is not None and host.lower() not in _ALLOWED_HOSTS:
            continue
        url_path = match.group("path")
        asset = _asset_from_url_path(url_path)
        if asset is None or asset == SW_PATH:
            continue
        found.append((asset, url_path, match.group("version")))
    return found


def cache_name_of(sw_text: str) -> str | None:
    match = _CACHE_NAME_RE.search(sw_text or "")
    if not match:
        return None
    return match.group("value")


def static_assets_body(sw_text: str) -> str:
    match = _STATIC_ASSETS_RE.search(sw_text or "")
    if not match:
        return ""
    return match.group("body")


def _index_refs(files: dict[str, str]) -> dict[str, dict[str, list[tuple[str, str]]]]:
    """asset -> source file -> [(url path, version), ...]."""
    indexed: dict[str, dict[str, list[tuple[str, str]]]] = {}
    for source, text in files.items():
        norm = source.replace("\\", "/").strip()
        if not is_reference_source(norm):
            continue
        for asset, url_path, version in extract_versioned_refs(text):
            indexed.setdefault(asset, {}).setdefault(norm, []).append((url_path, version))
    return indexed


def _html_versions(index: dict[str, dict[str, list[tuple[str, str]]]]) -> dict[str, set[str]]:
    versions: dict[str, set[str]] = {}
    for asset, sources in index.items():
        for source, entries in sources.items():
            if not source.endswith(".html"):
                continue
            versions.setdefault(asset, set()).update(version for _path, version in entries)
    return versions


def _static_versions(sw_text: str) -> dict[str, set[str]]:
    versions: dict[str, set[str]] = {}
    for asset, _url_path, version in extract_versioned_refs(static_assets_body(sw_text)):
        versions.setdefault(asset, set()).add(version)
    return versions


def _static_ref_tuples(asset: str, sw_text: str) -> list[tuple[str, str, str]]:
    tuples: list[tuple[str, str, str]] = []
    for ref_asset, url_path, version in extract_versioned_refs(static_assets_body(sw_text)):
        if ref_asset == asset:
            tuples.append(("viewer/sw.js STATIC_ASSETS", url_path, version))
    return tuples


def _html_ref_tuples(
    asset: str,
    index: dict[str, dict[str, list[tuple[str, str]]]],
) -> list[tuple[str, str, str]]:
    tuples: list[tuple[str, str, str]] = []
    for source, entries in index.get(asset, {}).items():
        if source.endswith(".html"):
            for url_path, version in entries:
                tuples.append((source, url_path, version))
    return tuples


def _join_refs(refs: list[tuple[str, str, str]]) -> str:
    unique = sorted(set(refs))
    return ", ".join(f"{source} references {path}?v={version}" for source, path, version in unique)


def _unbumped_messages(
    asset: str,
    base_sources: dict[str, list[tuple[str, str]]],
    head_sources: dict[str, list[tuple[str, str]]],
) -> list[str]:
    messages: list[str] = []
    for source in sorted(head_sources):
        base_versions = {version for _path, version in base_sources.get(source, [])}
        reported: set[str] = set()
        for url_path, version in head_sources[source]:
            if version in base_versions and version not in reported:
                reported.add(version)
                messages.append(
                    f"{asset} changed but {source} still references {url_path}?v={version}; "
                    f"bump that ?v= cache buster."
                )
    return messages


def _cache_name_message(
    base_sw: str,
    head_sw: str,
    assets: list[str],
    sw_changed: bool,
) -> str | None:
    if not assets and not sw_changed:
        return None
    base_name = cache_name_of(base_sw)
    head_name = cache_name_of(head_sw)
    if head_name is not None and head_name != base_name:
        return None
    shown = head_name if head_name is not None else base_name
    if shown is None:
        name_bit = "viewer/sw.js CACHE_NAME is missing"
    else:
        name_bit = f"viewer/sw.js CACHE_NAME is unchanged ({shown!r})"
    if assets and sw_changed:
        subject = f"{', '.join(assets)} changed and viewer/sw.js changed but {name_bit}"
    elif assets:
        subject = f"{', '.join(assets)} changed but {name_bit}"
    else:
        subject = f"viewer/sw.js changed but {name_bit}"
    return (
        f"{subject}; bump CACHE_NAME so returning visitors drop the stale service worker cache."
    )


def _mismatch_message(asset: str, html_refs: list[tuple[str, str, str]], sw_refs: list[tuple[str, str, str]]) -> str:
    html_text = _join_refs(html_refs) if html_refs else "no HTML ?v= reference"
    sw_text = _join_refs(sw_refs) if sw_refs else "no viewer/sw.js STATIC_ASSETS ?v= reference"
    return (
        f"{asset} versions disagree between HTML and viewer/sw.js STATIC_ASSETS: "
        f"{html_text}; {sw_text}."
    )


def cache_buster_violations(
    changed_paths: list[str],
    base_files: dict[str, str],
    head_files: dict[str, str],
) -> list[str]:
    """Return one message per stale reference, CACHE_NAME miss, or version mismatch.

    `base_files` and `head_files` map repo paths (viewer HTML and viewer/sw.js)
    to file text. An empty list means the diff is safe to merge.
    """
    changed = [path.replace("\\", "/").strip() for path in changed_paths if path.strip()]
    asset_changes = sorted({path for path in changed if is_viewer_code_asset(path)})
    sw_changed = SW_PATH in changed

    base_index = _index_refs(base_files)
    head_index = _index_refs(head_files)
    referenced: set[str] = set()
    for index in (base_index, head_index):
        referenced.update(index)
    touched = [asset for asset in asset_changes if asset in referenced]

    failures: list[str] = []
    for asset in touched:
        failures.extend(
            _unbumped_messages(
                asset,
                base_index.get(asset, {}),
                head_index.get(asset, {}),
            )
        )

    cache_message = _cache_name_message(
        base_files.get(SW_PATH, ""),
        head_files.get(SW_PATH, ""),
        touched,
        sw_changed,
    )
    if cache_message:
        failures.append(cache_message)

    base_html = _html_versions(base_index)
    head_html = _html_versions(head_index)
    base_static = _static_versions(base_files.get(SW_PATH, ""))
    head_static = _static_versions(head_files.get(SW_PATH, ""))
    mismatch_assets = set(touched)
    for asset in set(base_html) | set(head_html) | set(base_static) | set(head_static):
        html_changed = base_html.get(asset, set()) != head_html.get(asset, set())
        static_changed = base_static.get(asset, set()) != head_static.get(asset, set())
        if html_changed or static_changed:
            mismatch_assets.add(asset)
    mismatch_assets.discard(SW_PATH)

    head_sw = head_files.get(SW_PATH, "")
    for asset in sorted(mismatch_assets):
        html_set = head_html.get(asset, set())
        static_set = head_static.get(asset, set())
        if html_set == static_set:
            continue
        failures.append(
            _mismatch_message(
                asset,
                _html_ref_tuples(asset, head_index),
                _static_ref_tuples(asset, head_sw),
            )
        )
    return failures


def _scan_required(paths: list[str]) -> bool:
    for path in paths:
        norm = path.replace("\\", "/")
        if norm == SW_PATH or is_viewer_code_asset(norm):
            return True
    return False


def reference_sources(rev: str) -> list[str]:
    out = _git("ls-tree", "-r", "--name-only", rev, "viewer")
    return [line for line in out.splitlines() if is_reference_source(line)]


def read_blobs(rev: str, paths: list[str]) -> dict[str, str]:
    if not paths:
        return {}
    proc = subprocess.Popen(
        ["git", "cat-file", "--batch"],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    payload = "".join(f"{rev}:{path}\n" for path in paths).encode()
    stdout, stderr = proc.communicate(payload)
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode,
            ["git", "cat-file", "--batch"],
            stderr=stderr,
        )
    return _parse_cat_file_batch(paths, stdout)


def _parse_cat_file_batch(paths: list[str], blob: bytes) -> dict[str, str]:
    out: dict[str, str] = {}
    offset = 0
    total = len(blob)
    for path in paths:
        if offset >= total:
            break
        newline = blob.find(b"\n", offset)
        if newline < 0:
            break
        header = blob[offset:newline].decode()
        offset = newline + 1
        parts = header.split()
        if not parts or parts[-1] == "missing":
            continue
        size = int(parts[-1])
        data = blob[offset : offset + size]
        offset += size
        if offset < total and blob[offset : offset + 1] == b"\n":
            offset += 1
        out[path] = data.decode("utf-8", errors="replace")
    return out


def main() -> int:
    base = resolve_base()
    if base is None:
        print("No cache-buster base commit; no viewer asset changes to check.")
        return 0
    try:
        _git("rev-parse", "--verify", f"{base}^{{commit}}")
    except subprocess.CalledProcessError:
        print(f"Cache-buster base commit is not available: {base}", file=sys.stderr)
        return 1

    changed = changed_paths(base)
    if not _scan_required(changed):
        print(f"No viewer JS/CSS asset changes that require a cache-buster bump (base {base}).")
        return 0

    base_files = read_blobs(base, reference_sources(base))
    head_files = read_blobs("HEAD", reference_sources("HEAD"))
    failed = cache_buster_violations(changed, base_files, head_files)
    if not failed:
        print(f"Viewer cache busters match changed JS/CSS assets (base {base}).")
        return 0
    print(
        "Viewer JS/CSS changes are missing cache-buster bumps "
        "(every ?v= reference and viewer/sw.js CACHE_NAME):",
        file=sys.stderr,
    )
    for item in failed:
        print(f"  {item}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"")
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", errors="replace")
        print(detail.strip() or f"git command failed: {exc.cmd}", file=sys.stderr)
        raise SystemExit(1)

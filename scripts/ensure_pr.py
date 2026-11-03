#!/usr/bin/env python3
"""ensure_pr.py — idempotent PR creator (recreated 2026-10-27; original lost
in sandbox reset, behavior restored from session record).

Usage: python3 scripts/ensure_pr.py <token> <head> <base> <title> <body_file>

Steps:
  1. verify head/base refs exist on origin (GET)
  2. idempotence: if an OPEN pr with same head+base exists, report it
  3. else create the PR (title + body from file)
  4. poll mergeable state once and print it

Token is passed via argv only; never written to disk or git config.
"""
import json
import sys
import time
import urllib.request

API = "https://api.github.com/repos/NickAiNYC/Propstein"


def req(method, url, token, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    r = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "propwire-ensure-pr",
    })
    with urllib.request.urlopen(r) as resp:
        body = resp.read().decode()
    return json.loads(body) if body else {}


def main():
    token, head, base, title, body_file = sys.argv[1:6]
    with open(body_file) as f:
        body = f.read()

    # 1. refs exist?
    for ref in (head, base):
        got = req("GET", f"{API}/git/ref/heads/{ref}", token)
        sha = (got.get("object") or {}).get("sha", "?")[:7]
        print(f"ref {ref} -> {sha}")

    # 2. idempotent: existing open pr?
    prs = req("GET", f"{API}/pulls?head=NickAiNYC:{head}&base={base}&state=open",
              token)
    if isinstance(prs, list) and prs:
        pr = prs[0]
        print(f"PR #{pr['number']} already open: {pr['html_url']}")
        print(f"mergeable={pr.get('mergeable')} state={pr.get('mergeable_state')}")
        return

    # 3. create
    pr = req("POST", f"{API}/pulls", token, {
        "title": title, "head": head, "base": base, "body": body})
    print(f"created PR #{pr['number']}: {pr['html_url']}")

    # 4. one mergeable poll (may be None while CI computes)
    for _ in range(3):
        time.sleep(2)
        pr = req("GET", f"{API}/pulls/{pr['number']}", token)
        if pr.get("mergeable") is not None:
            break
    print(f"mergeable={pr.get('mergeable')} state={pr.get('mergeable_state')}")


if __name__ == "__main__":
    main()

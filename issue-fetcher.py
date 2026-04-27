#!/usr/bin/env python3
"""
Fetch all GitHub issues from a milestone (including comments) and write each issue
to a separate Markdown file.

Requirements:
  python3 -m pip install requests

Auth:
  export GITHUB_TOKEN="ghp_...yourtoken..."

Examples:
  ./fetch_milestone_issues.py --repo owner/name --milestone "v1.2.3" --out ./issues_md
  ./fetch_milestone_issues.py --repo owner/name --milestone 42 --out ./issues_md
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
import requests


API = "https://api.github.com"


def die(msg: str, code: int = 2) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def iso_to_utc(iso: Optional[str]) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return iso


def slugify_filename(s: str, max_len: int = 120) -> str:
    s = s.strip()
    s = re.sub(r"[^\w\s.-]", "", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s)
    s = s.replace(" ", "_")
    s = s.strip("._-")
    if not s:
        s = "issue"
    return s[:max_len]


def gh_headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "milestone-issue-exporter",
    }


def request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    headers: Dict[str, str],
    params: Optional[Dict[str, Any]] = None,
) -> requests.Response:
    while True:
        resp = session.request(method, url, headers=headers, params=params, timeout=60)
        if resp.status_code == 403 and resp.headers.get("X-RateLimit-Remaining") == "0":
            reset = resp.headers.get("X-RateLimit-Reset")
            if reset:
                wait_s = max(1, int(reset) - int(time.time()) + 2)
                print(f"rate limit hit, sleeping {wait_s}s...", file=sys.stderr)
                time.sleep(wait_s)
                continue
        if resp.status_code in (502, 503, 504):
            time.sleep(2)
            continue
        return resp


def paginate(
    session: requests.Session,
    url: str,
    headers: Dict[str, str],
    params: Optional[Dict[str, Any]] = None,
) -> Iterable[Dict[str, Any]]:
    page = 1
    per_page = 100
    while True:
        p = dict(params or {})
        p.update({"per_page": per_page, "page": page})
        resp = request_with_retry(session, "GET", url, headers, params=p)
        if resp.status_code != 200:
            die(f"GET {url} failed: {resp.status_code} {resp.text[:500]}")
        items = resp.json()
        if not isinstance(items, list):
            die(f"expected list from {url}, got {type(items).__name__}")
        if not items:
            return
        for it in items:
            yield it
        if len(items) < per_page:
            return
        page += 1


def get_repo_parts(repo: str) -> Tuple[str, str]:
    if "/" not in repo:
        die("--repo must be in owner/name form")
    owner, name = repo.split("/", 1)
    owner = owner.strip()
    name = name.strip()
    if not owner or not name:
        die("--repo must be in owner/name form")
    return owner, name


def resolve_milestone_number(
    session: requests.Session,
    headers: Dict[str, str],
    owner: str,
    repo: str,
    milestone: str,
) -> int:
    if milestone.isdigit():
        return int(milestone)

    url = f"{API}/repos/{owner}/{repo}/milestones"
    candidates: List[Dict[str, Any]] = []
    for state in ("open", "closed", "all"):
        ms = list(paginate(session, url, headers, params={"state": state}))
        for m in ms:
            if str(m.get("title", "")).strip() == milestone.strip():
                return int(m["number"])
        candidates.extend(ms)

    titles = sorted({str(m.get("title", "")) for m in candidates if m.get("title")})
    hint = ""
    if titles:
        hint = "\navailable milestone titles:\n" + "\n".join(f"  - {t}" for t in titles[:100])
    die(f'milestone title not found: "{milestone}"{hint}')
    return 0


def fetch_issue_comments(
    session: requests.Session,
    headers: Dict[str, str],
    owner: str,
    repo: str,
    issue_number: int,
) -> List[Dict[str, Any]]:
    url = f"{API}/repos/{owner}/{repo}/issues/{issue_number}/comments"
    return list(paginate(session, url, headers))


def render_issue_markdown(
    repo_full: str,
    issue: Dict[str, Any],
    comments: List[Dict[str, Any]],
) -> str:
    number = issue.get("number")
    title = issue.get("title") or ""
    state = issue.get("state") or ""
    html_url = issue.get("html_url") or ""
    created_at = iso_to_utc(issue.get("created_at"))
    updated_at = iso_to_utc(issue.get("updated_at"))
    closed_at = iso_to_utc(issue.get("closed_at"))
    user = (issue.get("user") or {}).get("login") or ""
    assignees = ", ".join([(a.get("login") or "") for a in (issue.get("assignees") or []) if a.get("login")]) or ""
    labels = ", ".join([(l.get("name") or "") for l in (issue.get("labels") or []) if l.get("name")]) or ""
    milestone_title = ((issue.get("milestone") or {}).get("title")) or ""
    body = issue.get("body") or ""

    pr_hint = ""
    if issue.get("pull_request"):
        pr_hint = "This item is a pull request."

    lines: List[str] = []
    lines.append(f"# #{number} {title}")
    lines.append("")
    lines.append(f"Repo: {repo_full}")
    lines.append(f"URL: {html_url}")
    lines.append(f"State: {state}")
    if pr_hint:
        lines.append(pr_hint)
    lines.append(f"Author: {user}")
    if assignees:
        lines.append(f"Assignees: {assignees}")
    if labels:
        lines.append(f"Labels: {labels}")
    if milestone_title:
        lines.append(f"Milestone: {milestone_title}")
    if created_at:
        lines.append(f"Created: {created_at}")
    if updated_at:
        lines.append(f"Updated: {updated_at}")
    if closed_at:
        lines.append(f"Closed: {closed_at}")
    lines.append("")
    lines.append("## Body")
    lines.append("")
    lines.append(body.strip() if body.strip() else "_(no body)_")
    lines.append("")
    lines.append(f"## Comments ({len(comments)})")
    lines.append("")

    for c in comments:
        c_user = (c.get("user") or {}).get("login") or ""
        c_created = iso_to_utc(c.get("created_at"))
        c_updated = iso_to_utc(c.get("updated_at"))
        c_url = c.get("html_url") or ""
        c_body = c.get("body") or ""
        lines.append(f"### {c_user} at {c_created}")
        if c_url:
            lines.append(f"{c_url}")
        if c_updated and c_updated != c_created:
            lines.append(f"Updated: {c_updated}")
        lines.append("")
        lines.append(c_body.strip() if c_body.strip() else "_(empty comment)_")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def yaml_escape(s: str) -> str:
    """Wrap a string in double quotes if it contains YAML-unsafe characters."""
    if any(c in s for c in ('"', "'", ':', '#', '[', ']', '{', '}', ',', '&', '*', '?', '|', '-', '<', '>', '=', '!', '%', '@', '`', '\n', '\r')):
        return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'
    return s


def render_known_issues_yaml(issues: List[Dict[str, Any]]) -> str:
    lines: List[str] = ["known_issues:"]
    for issue in issues:
        title = str(issue.get("title") or "")
        url = issue.get("html_url") or ""
        lines.append(f"  - description: {yaml_escape(title)}")
        lines.append(f"    url: {url}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Export GitHub issues to Markdown files.")
    ap.add_argument("--repo", required=True, help="owner/name")

    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument("--milestone", help='milestone number (e.g. 12) or title (e.g. "v1.2.3")')
    source.add_argument("--label", help='issue label name, e.g. "bug" or "help wanted"')

    ap.add_argument("--out", help="output directory for .md files (required unless --known-issues)")
    ap.add_argument("--state", default="all", choices=["open", "closed", "all"], help="issue state filter")
    ap.add_argument("--include-pull-requests", action="store_true", help="include PRs matching the filter")
    ap.add_argument("--known-issues", action="store_true",
                    help="output open issues as a YAML known_issues block (to --out file or stdout)")
    args = ap.parse_args()

    if not args.known_issues and not args.out:
        die("--out is required unless --known-issues is set")

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        die("GITHUB_TOKEN env var is required")

    owner, repo = get_repo_parts(args.repo)
    repo_full = f"{owner}/{repo}"

    with requests.Session() as session:
        headers = gh_headers(token)

        issues_url = f"{API}/repos/{owner}/{repo}/issues"

        if args.known_issues:
            query: Dict[str, Any] = {
                "state": "open",
                "sort": "created",
                "direction": "asc",
            }
            if args.milestone:
                ms_number = resolve_milestone_number(session, headers, owner, repo, args.milestone)
                query["milestone"] = ms_number
            if args.label:
                query["labels"] = args.label

            issues: List[Dict[str, Any]] = []
            for issue in paginate(session, issues_url, headers, params=query):
                if (not args.include_pull_requests) and issue.get("pull_request"):
                    continue
                issues.append(issue)

            yaml_output = render_known_issues_yaml(issues)

            if args.out:
                with open(args.out, "w", encoding="utf-8") as f:
                    f.write(yaml_output)
                print(f"wrote {args.out}", file=sys.stderr)
            else:
                sys.stdout.write(yaml_output)

            return 0

        os.makedirs(args.out, exist_ok=True)

        query = {
            "state": args.state,
            "sort": "created",
            "direction": "asc",
        }

        export_title = ""

        if args.milestone:
            ms_number = resolve_milestone_number(session, headers, owner, repo, args.milestone)
            query["milestone"] = ms_number
            export_title = f"Milestone export: {repo_full} / {args.milestone}"

        if args.label:
            query["labels"] = args.label
            export_title = f"Label export: {repo_full} / {args.label}"

        exported: List[Tuple[int, str]] = []
        for issue in paginate(session, issues_url, headers, params=query):
            if (not args.include_pull_requests) and issue.get("pull_request"):
                continue

            num = int(issue["number"])
            title = str(issue.get("title") or "")
            comments = fetch_issue_comments(session, headers, owner, repo, num)

            md = render_issue_markdown(repo_full, issue, comments)

            fname = f"{num:05d}_{slugify_filename(title)}.md"
            path = os.path.join(args.out, fname)
            with open(path, "w", encoding="utf-8") as f:
                f.write(md)

            exported.append((num, fname))
            print(f"wrote {path}")

        index_path = os.path.join(args.out, "_index.md")
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(f"# {export_title}\n\n")
            f.write(f"Exported at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n")
            for num, fname in exported:
                f.write(f"- #{num} {fname}\n")
        print(f"wrote {index_path}")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
fetch_github.py — Fetch all public repos for a GitHub user and build
RAG-ready chunks in memory/github.json.

Usage:
    python scripts/fetch_github.py
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

GITHUB_USER = "vishalramvelu"
GITHUB_API = "https://api.github.com"
OUTPUT_PATH = ROOT / "memory" / "github.json"
README_MAX_CHARS = 6000

# Config files worth fetching when present in the repo root
CONFIG_FILES = [
    "requirements.txt",
    "package.json",
    "Dockerfile",
    "docker-compose.yml",
]

log = logging.getLogger("fetch_github")
logging.basicConfig(level=logging.INFO, format="%(message)s")


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _headers(extra: dict | None = None) -> dict:
    h = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        h["Authorization"] = f"Bearer {token}"
    if extra:
        h.update(extra)
    return h


def _get(url: str, raw: bool = False, **kwargs) -> requests.Response:
    """GET with rate-limit awareness.  Set raw=True for raw file content."""
    headers = _headers({"Accept": "application/vnd.github.raw+json"} if raw else None)
    resp = requests.get(url, headers=headers, **kwargs)

    remaining = resp.headers.get("X-RateLimit-Remaining")
    if remaining and int(remaining) < 10:
        reset = resp.headers.get("X-RateLimit-Reset", "?")
        log.warning("  ⚠ Rate limit low: %s remaining (resets %s)", remaining, reset)
    if remaining and int(remaining) == 0:
        log.error("Rate limit exhausted. Try again later or set GITHUB_TOKEN.")
        raise SystemExit(1)

    resp.raise_for_status()
    return resp


# ---------------------------------------------------------------------------
# GitHub data fetchers
# ---------------------------------------------------------------------------

def fetch_repos() -> list[dict]:
    """Fetch all public repos, handling pagination."""
    repos, url = [], f"{GITHUB_API}/users/{GITHUB_USER}/repos"
    params = {"per_page": 100, "type": "public"}
    while url:
        resp = _get(url, params=params)
        repos.extend(resp.json())
        url = resp.links.get("next", {}).get("url")
        params = {}  # pagination URL already has params
    return repos


def fetch_languages(repo_name: str) -> dict:
    return _get(f"{GITHUB_API}/repos/{GITHUB_USER}/{repo_name}/languages").json()


def fetch_readme(repo_name: str) -> str | None:
    try:
        return _get(f"{GITHUB_API}/repos/{GITHUB_USER}/{repo_name}/readme", raw=True).text
    except requests.HTTPError:
        return None


def fetch_root_listing(repo_name: str) -> list[dict]:
    try:
        return _get(f"{GITHUB_API}/repos/{GITHUB_USER}/{repo_name}/contents/").json()
    except requests.HTTPError:
        return []


def fetch_file(repo_name: str, path: str) -> str | None:
    try:
        return _get(f"{GITHUB_API}/repos/{GITHUB_USER}/{repo_name}/contents/{path}", raw=True).text
    except requests.HTTPError:
        return None


def fetch_workflows(repo_name: str) -> list[str]:
    """Return list of workflow filenames, or [] if none."""
    try:
        items = _get(f"{GITHUB_API}/repos/{GITHUB_USER}/{repo_name}/contents/.github/workflows").json()
        return [i["name"] for i in items if i["name"].endswith((".yml", ".yaml"))]
    except requests.HTTPError:
        return []


# ---------------------------------------------------------------------------
# Chunk builders
# ---------------------------------------------------------------------------

def _slug(name: str) -> str:
    """Normalise repo name to a chunk-ID-safe slug."""
    return name.lower().replace("-", "_").replace(".", "_")


def _fmt_languages(langs: dict) -> str:
    total = sum(langs.values()) or 1
    parts = [f"{lang} ({bytes_/total*100:.0f}%)" for lang, bytes_ in langs.items()]
    return ", ".join(parts) if parts else "None detected"


def build_overview(repo: dict, langs: dict) -> dict:
    name = repo["name"]
    desc = repo.get("description") or "No description provided."
    topics = ", ".join(repo.get("topics") or []) or "None"
    text = (
        f"GitHub project: {name} (github.com/{GITHUB_USER}/{name}).\n"
        f"Description: {desc}\n"
        f"Primary language: {repo.get('language') or 'N/A'}. "
        f"All languages: {_fmt_languages(langs)}.\n"
        f"Topics: {topics}.\n"
        f"Stars: {repo.get('stargazers_count', 0)}, "
        f"Forks: {repo.get('forks_count', 0)}.\n"
        f"Created: {repo['created_at'][:10]}, "
        f"Last updated: {repo['updated_at'][:10]}."
    )
    tags = [name, "github", repo.get("language") or "unknown"]
    tags += repo.get("topics") or []
    return {
        "id": f"gh_{_slug(name)}_overview",
        "category": "github_project",
        "tags": tags,
        "text": text,
    }


def build_readme(repo: dict, readme: str) -> dict | None:
    if not readme or not readme.strip():
        return None
    name = repo["name"]
    truncated = readme[:README_MAX_CHARS]
    if len(readme) > README_MAX_CHARS:
        truncated += "\n[... truncated]"
    text = f"README for GitHub project {name}:\n\n{truncated}"
    return {
        "id": f"gh_{_slug(name)}_readme",
        "category": "github_project",
        "tags": [name, "github", "readme", repo.get("language") or "unknown"],
        "text": text,
    }


def build_techstack(repo: dict, root_listing: list[dict],
                    config_files: dict[str, str], workflows: list[str]) -> dict | None:
    name = repo["name"]
    parts = []

    # Directory listing
    entries = sorted(i["name"] + ("/" if i["type"] == "dir" else "") for i in root_listing)
    if entries:
        parts.append(f"Top-level files and directories: {', '.join(entries)}")

    # Config files
    if "requirements.txt" in config_files:
        parts.append(f"Python dependencies (requirements.txt):\n{config_files['requirements.txt']}")
    if "package.json" in config_files:
        try:
            pkg = json.loads(config_files["package.json"])
            deps = list((pkg.get("dependencies") or {}).keys())
            dev = list((pkg.get("devDependencies") or {}).keys())
            parts.append(
                f"Node.js project: {pkg.get('name', name)}. "
                f"Dependencies: {', '.join(deps) or 'none'}. "
                f"Dev dependencies: {', '.join(dev) or 'none'}."
            )
        except json.JSONDecodeError:
            parts.append(f"package.json (could not parse): {config_files['package.json'][:500]}")
    if "Dockerfile" in config_files:
        from_line = next(
            (l.strip() for l in config_files["Dockerfile"].splitlines() if l.strip().upper().startswith("FROM")),
            "unknown",
        )
        parts.append(f"Has Dockerfile. Base image: {from_line}")
    if "docker-compose.yml" in config_files:
        parts.append(f"Has docker-compose.yml.")
    if workflows:
        parts.append(f"CI/CD: GitHub Actions workflows: {', '.join(workflows)}")

    if not parts:
        return None

    text = f"Tech stack and structure for GitHub project {name}:\n\n" + "\n".join(parts)
    tags = [name, "github", "techstack"]
    return {
        "id": f"gh_{_slug(name)}_techstack",
        "category": "github_project",
        "tags": tags,
        "text": text,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not os.environ.get("GITHUB_TOKEN"):
        log.warning("GITHUB_TOKEN not set — using unauthenticated API (60 req/hr limit)")

    log.info("Fetching public repos for %s ...", GITHUB_USER)
    repos = fetch_repos()
    log.info("Found %d public repos", len(repos))

    all_chunks: list[dict] = []

    for repo in repos:
        name = repo["name"]
        log.info("  → %s", name)
        try:
            langs = fetch_languages(name)
            readme = fetch_readme(name)
            root = fetch_root_listing(name)

            root_names = {i["name"] for i in root}
            configs = {}
            for cf in CONFIG_FILES:
                if cf in root_names:
                    content = fetch_file(name, cf)
                    if content:
                        configs[cf] = content

            workflows = fetch_workflows(name) if ".github" in root_names else []

            all_chunks.append(build_overview(repo, langs))
            rc = build_readme(repo, readme)
            if rc:
                all_chunks.append(rc)
            tc = build_techstack(repo, root, configs, workflows)
            if tc:
                all_chunks.append(tc)

        except requests.HTTPError as e:
            log.warning("  ✗ Skipping %s: %s", name, e)
        except Exception as e:
            log.warning("  ✗ Skipping %s: %s", name, e)

    output = {
        "meta": {
            "source": "github_api",
            "github_user": GITHUB_USER,
            "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "schema_version": "2.0",
            "repo_count": len(repos),
        },
        "chunks": all_chunks,
    }

    OUTPUT_PATH.write_text(json.dumps(output, indent=2))
    log.info("Wrote %d chunks for %d repos → %s", len(all_chunks), len(repos), OUTPUT_PATH)


if __name__ == "__main__":
    main()

"""Check publishable Skill metadata, local links and repository hygiene.

By default, inspect Git-visible files; --history also checks reachable old blobs
and commit identities. Ignored local run data stays private.
This is not a live-source or semantic quality certification.
"""
import argparse
import io
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_PATH = re.compile(r"/(?:Users|home)/[A-Za-z0-9_.-]+/")
SECRET = re.compile(
    r"(?:sk-[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}|"
    r"AIza[0-9A-Za-z_-]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)

PERSONAL_EMAIL = re.compile(
    r"[\w.+-]+@(?:gmail|outlook|hotmail|qq|163|126|icloud)\.com", re.I,
)


def privacy_findings(name, text):
    """Return categories only, never print matched private values."""
    findings = []
    if PRIVATE_PATH.search(text):
        findings.append("personal machine path")
    if PERSONAL_EMAIL.search(text):
        findings.append("personal email")
    for match in SECRET.finditer(text):
        if name.startswith("tests/") and re.fullmatch(r"ghp_x+", match.group()):
            continue
        findings.append("credential-shaped content")
        break
    return findings


def check_history(root):
    """Inspect unique reachable blobs and commit identities across local refs."""
    rows = subprocess.check_output(
        ["git", "rev-list", "--objects", "--all"], cwd=root,
    ).decode().splitlines()
    objects = [row.split(" ", 1) for row in rows if " " in row]
    payload = subprocess.check_output(
        ["git", "cat-file", "--batch"], cwd=root,
        input="".join(oid + "\n" for oid, _ in objects).encode(),
    )
    stream = io.BytesIO(payload)
    errors = []
    blobs = 0
    for _, name in objects:
        header = stream.readline().decode().strip().split()
        if len(header) != 3 or header[1] not in {"blob", "tree", "commit", "tag"}:
            raise ValueError("unexpected git cat-file response")
        content = stream.read(int(header[2]))
        if stream.read(1) != b"\n":
            raise ValueError("incomplete git object response")
        if header[1] != "blob":
            continue
        blobs += 1
        for category in privacy_findings(name, content.decode("utf-8", errors="replace")):
            errors.append(f"history {header[0][:12]} {name}: {category}")
    identities = subprocess.check_output(
        ["git", "log", "--all", "--format=%ae%n%ce"], cwd=root,
    ).decode().splitlines()
    personal = {value for value in identities if PERSONAL_EMAIL.search(value)}
    if personal:
        errors.append(f"history: {len(personal)} personal email(s) in commit identities")
    return {"blobs": blobs, "errors": errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="store_true", help="also scan reachable Git history and commit identities")
    args = parser.parse_args()
    files = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT,
    ).decode().split("\0")
    files = sorted(set(name for name in files if name))
    errors = []
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    parts = skill.split("---", 2)
    meta = yaml.safe_load(parts[1]) if len(parts) == 3 and not parts[0].strip() else None
    if not isinstance(meta, dict):
        errors.append("SKILL.md: missing YAML frontmatter")
        meta = {}
    name = str(meta.get("name", ""))
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) or len(name) > 64:
        errors.append("SKILL.md: invalid skill name")
    if not isinstance(meta.get("description"), str) or not 1 <= len(meta["description"].strip()) <= 1024:
        errors.append("SKILL.md: description must be 1–1024 characters")
    compatibility = meta.get("compatibility")
    if compatibility is not None and (not isinstance(compatibility, str) or not 1 <= len(compatibility) <= 500):
        errors.append("SKILL.md: compatibility must be 1–500 characters")
    if len(skill.splitlines()) >= 500:
        errors.append("SKILL.md: split conditional detail into references")
    interface = yaml.safe_load((ROOT / "agents/openai.yaml").read_text(encoding="utf-8"))
    if f"${name}" not in interface.get("interface", {}).get("default_prompt", ""):
        errors.append("agents/openai.yaml: default prompt must invoke this skill")

    links = 0
    forbidden = {".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache", "build", "dist", "runs", ".cache", ".pytest_tmp"}
    for name in files:
        path = ROOT / name
        if any(part in forbidden or part.endswith(".egg-info") for part in Path(name).parts):
            errors.append(f"{name}: generated or private artifact in publishable tree")
        if path.name == ".DS_Store" or path.name == ".env" or path.name.startswith(".env.") or path.suffix in {".pem", ".key", ".pyc"}:
            errors.append(f"{name}: local configuration, secret material or generated file")
        if not path.is_file():
            continue
        if path.stat().st_size > 1_000_000:
            errors.append(f"{name}: oversized file; keep raw data in ignored runs/")
        text = path.read_text(encoding="utf-8", errors="replace")
        for category in privacy_findings(name, text):
            errors.append(f"{name}: {category} in publishable file")
        if path.suffix != ".md" or "archive" in path.parts or "tests" in path.parts:
            continue
        body = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.S)
        for target in re.findall(r"\]\(([^)]+)\)", body):
            target = target.split(' "', 1)[0].strip("<>")
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            dest = (path.parent / unquote(parsed.path)).resolve()
            links += 1
            if not dest.exists():
                errors.append(f"{name}: broken local link {target}")
            elif not dest.is_relative_to(ROOT):
                errors.append(f"{name}: local link escapes the repository: {target}")
    history = check_history(ROOT) if args.history else None
    if history:
        errors.extend(history["errors"])
    report = {"status": "FAIL" if errors else "PASS", "files": len(files), "local_links": links, "errors": errors}
    if history:
        report["history_blobs"] = history["blobs"]
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return bool(errors)


if __name__ == "__main__":
    sys.exit(main())

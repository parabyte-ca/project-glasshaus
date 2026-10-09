#!/usr/bin/env python3
"""Keep release references in step with VERSION and CHANGELOG.md.

- CHANGELOG.md: the compare links at the bottom are rebuilt from the "## [x.y.z]" headings.
- README.md: the "> **Status:**" line names the current version.

    scripts/release_docs.py          rewrite both files
    scripts/release_docs.py --check  exit 1 if either is out of date (CI, pre-commit)
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "https://github.com/parabyte-ca/project-glasshaus"
STATUS = re.compile(r"^> \*\*Status:\*\* v\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?", re.M)


def changelog(text: str) -> str:
    versions = re.findall(r"^## \[(\d+\.\d+\.\d+[^\]]*)\]", text, re.M)
    body = re.sub(r"\n(\[[^\]]+\]: \S+\n?)+\s*$", "\n", text).rstrip("\n")
    links = [f"[Unreleased]: {REPO}/compare/v{versions[0]}...HEAD"] if versions else []
    for newer, older in zip(versions, versions[1:], strict=False):
        links.append(f"[{newer}]: {REPO}/compare/v{older}...v{newer}")
    if versions:
        links.append(f"[{versions[-1]}]: {REPO}/releases/tag/v{versions[-1]}")
    return body + "\n\n" + "\n".join(links) + "\n"


def readme(text: str, version: str) -> str:
    if not STATUS.search(text):
        raise SystemExit("README.md has no '> **Status:** vX.Y.Z' line")
    return STATUS.sub(f"> **Status:** v{version}", text, count=1)


def main() -> int:
    check = "--check" in sys.argv[1:]
    version = (ROOT / "VERSION").read_text().strip()
    stale = []
    for name, update in (("CHANGELOG.md", changelog), ("README.md", lambda t: readme(t, version))):
        path = ROOT / name
        old = path.read_text()
        new = update(old)
        if new != old:
            stale.append(name)
            if not check:
                path.write_text(new)
    if check and stale:
        print(f"out of date: {', '.join(stale)} (run scripts/release_docs.py)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

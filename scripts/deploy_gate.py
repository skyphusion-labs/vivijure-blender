"""Decide whether .github/workflows/deploy.yml may deploy the door Worker for this ref.

A pushed vX.Y.Z tag deploys only when CHANGELOG.md declares that release with a
`## X.Y.Z` heading, which is this repo's version of record (CLAUDE.md: bump the
CHANGELOG and the tag together). A workflow_dispatch deploys only from main.
Anything else is refused. The tag-on-main ancestry check is a separate step in
deploy.yml, the same as build-image.yml's assert-on-main, because it needs git
history.

Usage: deploy_gate.py <event_name> <ref> <path to CHANGELOG.md>
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

TAG = re.compile(r"refs/tags/v(\d+\.\d+\.\d+)")


def decide(event: str, ref: str, changelog: str) -> tuple[bool, str]:
    if event == "workflow_dispatch":
        if ref == "refs/heads/main":
            return True, "workflow_dispatch on main"
        return False, f"workflow_dispatch deploys only from main, not {ref}"
    if event != "push":
        return False, f"event {event} never deploys"
    match = TAG.fullmatch(ref)
    if match is None:
        return False, f"{ref} is not a vX.Y.Z tag"
    version = match.group(1)
    heading = re.compile(r"^## " + re.escape(version) + r"(?:\s|$)", re.MULTILINE)
    if heading.search(changelog) is None:
        return False, (
            f"tag v{version} has no '## {version}' heading in CHANGELOG.md; "
            "refusing to deploy a build the changelog does not declare"
        )
    return True, f"tag v{version} matches the '## {version}' heading in CHANGELOG.md"


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print("usage: deploy_gate.py <event_name> <ref> <CHANGELOG.md>", file=sys.stderr)
        return 2
    try:
        text = Path(argv[3]).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"::error::cannot read {argv[3]}: {exc}")
        return 1
    ok, why = decide(argv[1], argv[2], text)
    print(why if ok else f"::error::{why}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))

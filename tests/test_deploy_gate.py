"""scripts/deploy_gate.py: the ref and version gate in front of deploy.yml.

deploy.yml runs this file before the gate itself, so a gate that cannot refuse
stops the deploy.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("deploy_gate", ROOT / "scripts" / "deploy_gate.py")
assert _spec is not None and _spec.loader is not None
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)

LOG = "# Changelog\n\n## Unreleased\n\n## 0.3.0 -- 2026-11-10\n\n- x\n\n## 0.2.0 -- 2026-08-08\n"


def test_a_tag_with_its_release_heading_deploys() -> None:
    assert gate.decide("push", "refs/tags/v0.3.0", LOG)[0] is True
    assert gate.decide("push", "refs/tags/v0.2.0", LOG)[0] is True
    assert gate.decide("push", "refs/tags/v1.0.0", "## 1.0.0\n")[0] is True


def test_a_tag_the_changelog_does_not_declare_is_refused() -> None:
    ok, why = gate.decide("push", "refs/tags/v0.3.1", LOG)
    assert ok is False and "## 0.3.1" in why
    assert gate.decide("push", "refs/tags/v0.3.0", "## 0.3.01 -- x\n")[0] is False
    assert gate.decide("push", "refs/tags/v0.3.0", "### 0.3.0\n")[0] is False
    assert gate.decide("push", "refs/tags/v0.3.0", "- see ## 0.3.0\n")[0] is False
    assert gate.decide("push", "refs/tags/v0.3.0", "## Unreleased\n")[0] is False


def test_only_a_semver_v_tag_counts() -> None:
    for ref in ("refs/tags/v0.3", "refs/tags/0.3.0", "refs/tags/v0.3.0-rc1", "refs/tags/latest", "refs/heads/main"):
        assert gate.decide("push", ref, LOG)[0] is False, ref


def test_dispatch_deploys_only_from_main() -> None:
    assert gate.decide("workflow_dispatch", "refs/heads/main", LOG)[0] is True
    assert gate.decide("workflow_dispatch", "refs/heads/feature", LOG)[0] is False
    assert gate.decide("workflow_dispatch", "refs/tags/v0.3.0", LOG)[0] is False


def test_no_other_event_deploys() -> None:
    for event in ("pull_request", "pull_request_target", "schedule", ""):
        assert gate.decide(event, "refs/heads/main", LOG)[0] is False, event


def test_the_real_changelog_declares_0_2_0() -> None:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert gate.decide("push", "refs/tags/v0.2.0", text)[0] is True


def test_main_exit_codes(tmp_path: Path, capsys) -> None:
    log = tmp_path / "CHANGELOG.md"
    log.write_text(LOG, encoding="utf-8")
    assert gate.main(["g", "push", "refs/tags/v0.3.0", str(log)]) == 0
    assert gate.main(["g", "push", "refs/tags/v9.9.9", str(log)]) == 1
    assert "::error::" in capsys.readouterr().out
    assert gate.main(["g", "push", "refs/tags/v0.3.0", str(tmp_path / "missing.md")]) == 1
    assert gate.main(["g"]) == 2

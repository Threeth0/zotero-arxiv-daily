from pathlib import Path

import yaml


def test_daily_workflow_restores_serializes_and_persists_state():
    root = Path(__file__).resolve().parent.parent
    workflow = yaml.safe_load((root / ".github/workflows/main.yml").read_text())
    assert workflow["concurrency"]["cancel-in-progress"] is False
    steps = workflow["jobs"]["calculate-and-send"]["steps"]
    restore = next(step for step in steps if step.get("name") == "Restore recommendation state")
    persist = next(step for step in steps if step.get("name") == "Persist recommendation state")
    assert "recommendation-state" in restore["run"]
    assert persist["with"]["path"] == "state/recommendations.json"
    assert "always()" in persist["if"]
    checkout = next(step for step in steps if step.get("name") == "Checkout")
    assert "with" not in checkout
    runs = "\n".join(step.get("run", "") for step in steps)
    assert "CUSTOM_CONFIG" not in runs
    assert "--config-name github" in runs
    assert "--frozen" in runs
    assert workflow["jobs"]["calculate-and-send"]["timeout-minutes"] == 120
    triggers = workflow.get("on", workflow.get(True))
    assert triggers["schedule"] == [{"cron": "17 22 * * *"}]


def test_preview_workflow_does_not_invoke_live_delivery():
    root = Path(__file__).resolve().parent.parent
    workflow = yaml.safe_load((root / ".github/workflows/test.yml").read_text())
    runs = "\n".join(step.get("run", "") for step in workflow["jobs"]["calculate-and-send"]["steps"])
    assert "zotero_arxiv_daily.preview" in runs
    assert "zotero_arxiv_daily/main.py" not in runs
    assert "secrets." not in (root / ".github/workflows/test.yml").read_text()

from datetime import datetime, timezone
from pathlib import Path

from hydra import compose, initialize_config_dir
from omegaconf import OmegaConf, open_dict
import pytest

from zotero_arxiv_daily.policy import apply_daily_policy
from zotero_arxiv_daily.recommendation import RecommendationState


@pytest.mark.parametrize("count", [1, 10, 999, "${oc.env:MAX_PAPER_NUM}"])
def test_count_overrides_cannot_change_frozen_policy(config, monkeypatch, count):
    monkeypatch.setenv("MAX_PAPER_NUM", "2")
    with open_dict(config):
        config.executor.max_paper_num = count
        config.recommendation.enabled = False
        config.recommendation.external_count = 1
        config.recommendation.internal_count = 8
        config.recommendation.topic_targets = {"Other": 99}
    apply_daily_policy(config)
    assert config.executor.max_paper_num == 15
    assert config.recommendation.enabled is True
    assert config.recommendation.external_count == 12
    assert config.recommendation.internal_count == 3
    assert dict(config.recommendation.topic_targets) == {
        "VLN": 5, "Semantic Mapping": 4, "3D Reconstruction": 3, "SLAM": 3,
    }


def test_github_profile_has_no_custom_config_dependency(monkeypatch):
    env = {"ZOTERO_ID": "123", "ZOTERO_KEY": "fake", "SENDER": "from@example.org",
           "RECEIVER": "to@example.org", "SENDER_PASSWORD": "fake", "OPENAI_API_KEY": "fake",
           "OPENAI_API_BASE": "https://example.org/v1", "SMTP_PORT": "587", "LLM_MODEL": "test-model"}
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("CUSTOM_CONFIG", "executor:\n  max_paper_num: 1")
    root = Path(__file__).resolve().parent.parent
    with initialize_config_dir(config_dir=str(root / "config"), version_base=None):
        config = compose(config_name="github")
    apply_daily_policy(config)
    resolved = OmegaConf.to_container(config, resolve=True, throw_on_missing=True)
    assert resolved["executor"]["max_paper_num"] == 15
    assert resolved["email"]["smtp_port"] == 587
    assert resolved["llm"]["generation_kwargs"]["model"] == "test-model"
    assert resolved["executor"]["send_empty"] is True


def test_same_day_delivery_and_old_snapshot_upgrade(tmp_path):
    state = RecommendationState(tmp_path / "state.json")
    assert not state.delivered_on("2026-10-15")
    state.mark_sent([], datetime(2026, 10, 14, 23, tzinfo=timezone.utc), "2026-10-15")
    assert RecommendationState(state.path).delivered_on("2026-10-15")
    assert not state.delivered_on("2026-10-16")
    state.data.pop("deliveries")
    state.data["history"] = [{"keys": [], "origin": "external", "sent_at": "2026-10-14T23:00:00+00:00"}]
    state.save()
    assert RecommendationState(state.path).delivered_on("2026-10-15")


def test_main_enforces_policy_before_executor(config, monkeypatch):
    from zotero_arxiv_daily import main as main_mod
    seen = []
    class Executor:
        def __init__(self, cfg):
            seen.append((cfg.executor.max_paper_num, cfg.recommendation.external_count,
                         cfg.recommendation.internal_count, cfg.recommendation.enabled))
        def run(self):
            pass
    config.executor.max_paper_num = 2
    config.recommendation.enabled = False
    monkeypatch.setattr(main_mod, "Executor", Executor)
    main_mod.main.__wrapped__(config)
    assert seen == [(15, 12, 3, True)]

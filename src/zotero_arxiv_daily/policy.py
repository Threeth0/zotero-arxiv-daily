"""Version-controlled daily policy, applied AFTER all Hydra/env overrides.

Changing these rules intentionally requires a code change, not an Actions variable.
Targets remain soft and origin caps are not force-filled.
"""

from types import MappingProxyType

from loguru import logger
from omegaconf import OmegaConf


MAX_DAILY_PAPERS = 15
EXTERNAL_PAPERS = 12
INTERNAL_PAPERS = 3
TOPIC_TARGETS = MappingProxyType({
    "VLN": 5, "Semantic Mapping": 4, "3D Reconstruction": 3, "SLAM": 3,
})


def apply_daily_policy(config):
    """Overwrite protected options without resolving untrusted old values."""
    fixed = {
        "executor.max_paper_num": MAX_DAILY_PAPERS,
        "recommendation.enabled": True,
        "recommendation.external_count": EXTERNAL_PAPERS,
        "recommendation.internal_count": INTERNAL_PAPERS,
        "recommendation.topic_targets": dict(TOPIC_TARGETS),
    }
    for key, value in fixed.items():
        OmegaConf.update(config, key, value, merge=False, force_add=True)
    logger.info("Fixed daily policy: at most 15 papers; external 12 + internal 3; soft topics 5/4/3/3")
    return config

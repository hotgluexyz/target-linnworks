"""Tests standard target features using the built-in SDK tests library."""

import json
import os
from typing import Any, Dict

import pytest

from hotglue_singer_sdk.testing import get_standard_target_tests

from target_linnworks.target import TargetLinnworks

SECRETS_PATH = os.path.join(os.path.dirname(__file__), "../../.secrets/config.json")


@pytest.fixture
def target_config() -> Dict[str, Any]:
    if not os.path.exists(SECRETS_PATH):
        pytest.skip("Secrets file not found; skipping integration tests.")
    with open(SECRETS_PATH) as f:
        return json.load(f)


def test_standard_target_tests(target_config):
    """Run standard target tests from the SDK."""
    tests = get_standard_target_tests(
        TargetLinnworks,
        config=target_config,
    )
    for test in tests:
        test()

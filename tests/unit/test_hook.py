"""Tests for the pre-commit hook."""

from __future__ import annotations

import os
from unittest.mock import patch

from src.hook import SEVERITY_ORDER, get_severity_threshold


class TestSeverityThreshold:
    def test_default_is_critical(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            # Remove SEVERITY_THRESHOLD if set
            os.environ.pop("SEVERITY_THRESHOLD", None)
            assert get_severity_threshold() == SEVERITY_ORDER["critical"]

    def test_warning_threshold(self) -> None:
        with patch.dict(os.environ, {"SEVERITY_THRESHOLD": "warning"}, clear=False):
            assert get_severity_threshold() == SEVERITY_ORDER["warning"]

    def test_suggestion_threshold(self) -> None:
        with patch.dict(os.environ, {"SEVERITY_THRESHOLD": "suggestion"}, clear=False):
            assert get_severity_threshold() == SEVERITY_ORDER["suggestion"]

    def test_info_threshold(self) -> None:
        with patch.dict(os.environ, {"SEVERITY_THRESHOLD": "info"}, clear=False):
            assert get_severity_threshold() == SEVERITY_ORDER["info"]

    def test_case_insensitive(self) -> None:
        with patch.dict(os.environ, {"SEVERITY_THRESHOLD": "WARNING"}, clear=False):
            assert get_severity_threshold() == SEVERITY_ORDER["warning"]

    def test_unknown_defaults_to_critical(self) -> None:
        with patch.dict(os.environ, {"SEVERITY_THRESHOLD": "invalid"}, clear=False):
            assert get_severity_threshold() == 0


class TestSeverityOrder:
    def test_ordering(self) -> None:
        assert SEVERITY_ORDER["critical"] < SEVERITY_ORDER["warning"]
        assert SEVERITY_ORDER["warning"] < SEVERITY_ORDER["suggestion"]
        assert SEVERITY_ORDER["suggestion"] < SEVERITY_ORDER["info"]

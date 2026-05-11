"""Pytest fixtures: isolated data dir so we don't poison the user's real db."""

from __future__ import annotations


import pytest


@pytest.fixture(autouse=True)
def _isolated_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("PAPERS_COOL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DISABLE_SCHEDULER", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    yield tmp_path

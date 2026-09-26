"""Shared fixtures. Every test runs offline: no network, no LLM call, no cache files."""

import socket
from pathlib import Path

import pytest

from gencite import cache, llm_client
from gencite.schema import GeneRecord, SynthResult
from gencite.synth_LLM import load_records

TEST_DATA = Path(__file__).parent.parent / "test_data"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Fail loudly if a test tries to reach an API or the LLM."""

    def no_network(*args, **kwargs):
        raise RuntimeError("network access in a test")

    def no_llm(*args, **kwargs):
        raise llm_client.LLMOutputError("LLM call in a test")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(llm_client, "chat", no_llm)
    monkeypatch.setattr(cache, "ENABLED", False)


@pytest.fixture
def records() -> dict[str, GeneRecord]:
    """Hand-written GeneRecords from test_data/dummy_records/."""
    return {r.gene.symbol: r for r in load_records([TEST_DATA / "dummy_records"])}


@pytest.fixture
def bad_claims() -> dict[str, SynthResult]:
    """Deliberately wrong claims from test_data/synth_bad/."""
    return {
        s.gene: s
        for s in (
            SynthResult.model_validate_json(f.read_text(encoding="utf-8"))
            for f in sorted((TEST_DATA / "synth_bad").glob("*.json"))
        )
    }

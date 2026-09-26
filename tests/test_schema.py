import pytest
from pydantic import ValidationError

from gencite.schema import Claim, GeneRecord, SynthResult


def test_dummy_records_are_valid(records):
    assert set(records) == {
        "ABCXYZ",
        "IRGM",
        "LINC02210-CRHR1",
        "MAGOH2P",
        "SPG7",
        "TMEM220",
    }
    assert not records["ABCXYZ"].gene.found


def test_claim_without_citation_is_rejected():
    with pytest.raises(ValidationError):
        Claim(text="uncited claim", evidence_ids=[])


def test_invalid_evidence_level_is_rejected():
    with pytest.raises(ValidationError):
        SynthResult(gene="X", evidence_level="maybe")


def test_evidence_without_id_is_rejected():
    with pytest.raises(ValidationError):
        GeneRecord.model_validate(
            {"gene": {"symbol": "X"}, "evidence": [{"source": "pubmed"}]}
        )

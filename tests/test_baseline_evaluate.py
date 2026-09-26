from gencite import baseline
from gencite.evaluate import evaluate, mentions
from gencite.schema import Claim, SynthResult
from gencite.verify import verify


def test_cited_pmid_missing_in_pubmed_becomes_invalid_id(monkeypatch):
    found = {
        "id": "PMID:1",
        "source": "pubmed",
        "title": "About something else",
        "text": "",
        "url": "",
    }
    monkeypatch.setattr(
        baseline, "fetch_pubmed_records", lambda pmids: [found] if "1" in pmids else []
    )
    synth = SynthResult(
        gene="GENEX",
        evidence_level="sufficient",
        claims=[
            Claim(text="a", evidence_ids=["PMID:1"]),
            Claim(text="b", evidence_ids=["PMID:2"]),
        ],
    )
    record = baseline.fetch_cited(synth)
    res = verify(synth, record, use_llm=False)
    assert [c.verdict for c in res.claims] == ["unchecked", "invalid_id"]

    m = evaluate(
        {"GENEX": res},
        {"GENEX": record},
        {"GENEX": {"kind": "clear", "expected": ["zzz"]}},
    )
    assert m["pmids"] == {
        "cited": 2,
        "not_found": 1,
        "off_topic": 1,
    }  # PMID:1 never names GENEX
    assert m["valid_citation"] == 1 and m["clear"]["GENEX"]["hit"] is False


def test_mentions_matches_whole_symbol_only():
    assert mentions("ERAP2", "ERAP2 trims peptides")
    assert not mentions("ERAP2", "ERAP1 and ERAP20")

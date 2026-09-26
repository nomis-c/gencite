import pytest

from gencite import collect_evidence as ce

GENE = {
    "found": True,
    "symbol": "X",
    "name": "x",
    "ensembl_id": "ENSG1",
    "entrez_id": "1",
}


@pytest.fixture
def fake_sources(monkeypatch):
    """Replace the four retrieval functions; PubMed and AMASS return the same paper."""
    paper = "https://pubmed.ncbi.nlm.nih.gov/123/"
    monkeypatch.setattr(
        ce,
        "retrieve_pubmed_evidence",
        lambda **k: [{"id": "PMID:123", "source": "pubmed", "url": paper}],
    )
    monkeypatch.setattr(
        ce,
        "retrieve_open_targets_evidence",
        lambda *a, **k: [{"id": "OT:1", "source": "open_targets", "url": ""}],
    )
    monkeypatch.setattr(ce, "retrieve_hpa_evidence", lambda *a: [])

    def amass_down(**kwargs):
        raise RuntimeError("AMASS down")

    monkeypatch.setattr(ce, "retrieve_amass_evidence", amass_down)


def test_all_sources_by_default_and_errors_are_recorded(fake_sources):
    rec = ce.collect_evidence(GENE)
    assert [e["id"] for e in rec["evidence"]] == ["PMID:123", "OT:1"]
    assert rec["errors"] == [{"source": "amass", "message": "AMASS down"}]
    assert rec["source_counts"] == {
        "pubmed": 1,
        "open_targets": 1,
        "human_protein_atlas": 0,
        "amass": 0,
    }


def test_only_selected_sources_are_queried(fake_sources):
    rec = ce.collect_evidence(GENE, enabled_sources={"open_targets"})
    assert [e["id"] for e in rec["evidence"]] == ["OT:1"]
    assert rec["errors"] == []


def test_unknown_source_is_rejected():
    with pytest.raises(ValueError, match="pubmd"):
        ce.collect_evidence(GENE, enabled_sources={"pubmd"})


def test_unresolved_gene_queries_nothing(fake_sources):
    rec = ce.collect_evidence({"found": False, "symbol": "ABCXYZ"})
    assert rec["evidence"] == [] and rec["errors"][0]["source"] == "gene_resolution"


def test_same_paper_from_pubmed_and_amass_is_kept_once():
    url = "https://pubmed.ncbi.nlm.nih.gov/123/"
    items = [
        {"id": "PMID:123", "source": "pubmed", "url": url},
        {"id": "AMASS:biomed:A", "source": "amass_biomedcore", "url": url + "/"},
        {"id": "PMID:123", "source": "pubmed", "url": url},
    ]
    assert [e["id"] for e in ce._deduplicate_evidence(items)] == ["PMID:123"]

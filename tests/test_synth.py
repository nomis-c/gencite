from gencite.synth_LLM import build_prompt, synthesize


def test_unresolved_gene_needs_no_llm(records):
    res = synthesize(records["ABCXYZ"])  # the LLM is blocked, so this must not call it
    assert res.evidence_level == "none" and res.claims == []
    assert "could not be resolved" in res.note


def test_gene_without_evidence_needs_no_llm(records):
    res = synthesize(records["MAGOH2P"])
    assert res.evidence_level == "none" and res.claims == []


def test_prompt_contains_every_evidence_id(records):
    prompt = build_prompt(records["IRGM"])
    assert all(f"[{e.id}]" in prompt for e in records["IRGM"].evidence)

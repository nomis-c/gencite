from gencite.schema import Claim
from gencite.verify import JUDGE_FAILED, check_ids, judge_failures, verify


def test_check_ids_returns_unknown_ids():
    claim = Claim(text="x", evidence_ids=["PMID:1", "PMID:2"])
    assert check_ids(claim, {"PMID:1"}) == ["PMID:2"]


def test_layer1_flags_made_up_and_foreign_ids(records, bad_claims):
    res = verify(bad_claims["IRGM"], records["IRGM"], use_llm=False)
    verdicts = [c.verdict for c in res.claims]
    assert verdicts.count("invalid_id") == 2
    assert res.claims[1].invalid_ids == ["PMID:99999999"]  # made up
    assert res.claims[2].invalid_ids == ["OT:function:SPG7"]  # belongs to another gene
    assert set(verdicts) == {"invalid_id", "unchecked"}


def test_judge_failure_marks_claim_unchecked_and_run_goes_on(records, bad_claims):
    res = verify(
        bad_claims["IRGM"], records["IRGM"], use_llm=True
    )  # LLM blocked -> every judge call fails
    judged = [c for c in res.claims if c.verdict != "invalid_id"]
    assert judged and all(c.verdict == "unchecked" for c in judged)
    assert all(c.reason.startswith(JUDGE_FAILED) for c in judged)
    assert judge_failures(res) == len(judged)

from gencite.create_report import build_report, counts
from gencite.verify import verify


def test_report_links_known_sources_and_not_invalid_ids(records, bad_claims):
    res = verify(bad_claims["IRGM"], records["IRGM"], use_llm=False)
    report = build_report([res], records)
    assert counts(res)["invalid_id"] == 2
    assert "`PMID:99999999`" in report and "[PMID:99999999](" not in report
    assert "[PMID:90000001](" in report

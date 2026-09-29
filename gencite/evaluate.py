"""Evaluation: compares a gencite run with the baseline on a fixed test set. Reads files only, no API or LLM calls.

    python -m gencite test_data/eval_genes.txt              # gencite  -> results/eval_genes/
    python -m gencite.baseline test_data/eval_genes.txt         # baseline -> results/eval_genes/baseline/
    python -m gencite.evaluate results/eval_genes               # -> results/eval_genes/evaluation.md + .json

The test set (test_data/eval_expected.json) marks each gene as "clear" (with terms a correct summary should
mention) or "negative" (pseudogene, unknown symbol: an honest answer says there is little or no evidence).
"""

import argparse
import json
import re
import sys
from pathlib import Path

from gencite.create_report import ORDER, _cell
from gencite.schema import GeneRecord, VerifyResult
from gencite.synth_LLM import load_records

SYSTEMS = {
    "gencite": "",
    "baseline": "baseline",
}  # system name -> subfolder of the run folder


def load_system(folder: Path) -> tuple[dict[str, VerifyResult], dict[str, GeneRecord]]:
    """VerifyResults and GeneRecords of one system (gencite or baseline), keyed by gene."""
    verified = {}
    for f in sorted((folder / "verified").glob("*.json")):
        res = VerifyResult.model_validate_json(f.read_text(encoding="utf-8"))
        verified[res.gene] = res
    records = (
        {r.gene.symbol: r for r in load_records([folder / "records"])}
        if (folder / "records").is_dir()
        else {}
    )
    return verified, records


def mentions(symbol: str, text: str) -> bool:
    """True if the text names the symbol as a whole word (ERAP2 does not match ERAP20)."""
    return (
        re.search(rf"(?<![A-Za-z0-9]){re.escape(symbol)}(?![A-Za-z0-9])", text, re.I)
        is not None
    )


def pmid_stats(res: VerifyResult, record: GeneRecord | None) -> dict[str, int]:
    """Unique cited PMIDs: how many exist in the gene's evidence, and how many of those never name the gene."""
    cited = {i for c in res.claims for i in c.evidence_ids if i.startswith("PMID:")}
    found = {e.id: e for e in record.evidence} if record else {}
    real = [found[i] for i in cited if i in found]
    return {
        "cited": len(cited),
        "not_found": len(cited) - len(real),
        "off_topic": sum(not mentions(res.gene, f"{e.title} {e.text}") for e in real),
    }


def evaluate(
    verified: dict[str, VerifyResult], records: dict[str, GeneRecord], expected: dict
) -> dict:
    """Metrics of one system: verdicts, cited PMIDs, expected terms (clear genes), honesty (negative controls)."""
    claims = [c for g in expected if g in verified for c in verified[g].claims]
    m = {
        "genes": sum(g in verified for g in expected),
        "missing": [g for g in expected if g not in verified],
        "claims": len(claims),
        "valid_citation": sum(c.verdict != "invalid_id" for c in claims),
        "verdicts": {v: sum(c.verdict == v for c in claims) for v in ORDER},
        "pmids": {"cited": 0, "not_found": 0, "off_topic": 0},
        "clear": {},
        "negative": {},
    }
    for gene, spec in expected.items():
        res = verified.get(gene)
        if res is None:
            continue
        for k, n in pmid_stats(res, records.get(gene)).items():
            m["pmids"][k] += n
        if spec["kind"] == "clear":
            text = " ".join(c.text for c in res.claims)
            hits = [t for t in spec["expected"] if t.lower() in text.lower()]
            m["clear"][gene] = {"hit": bool(hits), "terms": hits}
        else:
            m["negative"][gene] = {
                "honest": res.evidence_level != "sufficient",
                "evidence_level": res.evidence_level,
                "claims": len(res.claims),
            }
    return m


def failures(
    verified: dict[str, VerifyResult], expected: dict
) -> list[tuple[str, str, str, str]]:
    """Claims judged partial, unsupported or invalid_id, as (gene, verdict, claim, reason)."""
    return [
        (g, c.verdict, c.text, c.reason)
        for g in expected
        if g in verified
        for c in verified[g].claims
        if c.verdict in ("partial", "unsupported", "invalid_id")
    ]


def _pct(n: int, total: int) -> str:
    """ "84% (16/19)", or "–" if there is nothing to count."""
    return f"{100 * n / total:.0f}% ({n}/{total})" if total else "–"


def build_markdown(
    metrics: dict[str, dict], fails: dict[str, list], expected: dict
) -> str:
    """evaluation.md: metrics side by side, result per gene, failure cases of each system."""
    names = list(metrics)
    rows = [
        ("Genes evaluated", lambda m: str(m["genes"])),
        ("Claims", lambda m: str(m["claims"])),
        (
            "Claims with a valid citation (layer 1)",
            lambda m: _pct(m["valid_citation"], m["claims"]),
        ),
        (
            "Cited PMIDs that do not exist",
            lambda m: _pct(m["pmids"]["not_found"], m["pmids"]["cited"]),
        ),
        (
            "Cited PMIDs that never name the gene",
            lambda m: _pct(m["pmids"]["off_topic"], m["pmids"]["cited"]),
        ),
        *[
            (f"Claims judged `{v}`", lambda m, v=v: _pct(m["verdicts"][v], m["claims"]))
            for v in ORDER
        ],
        (
            "Clear genes: expected biology mentioned",
            lambda m: _pct(sum(x["hit"] for x in m["clear"].values()), len(m["clear"])),
        ),
        (
            "Negative controls: honest (not `sufficient`)",
            lambda m: _pct(
                sum(x["honest"] for x in m["negative"].values()), len(m["negative"])
            ),
        ),
        (
            "Negative controls: claims written",
            lambda m: str(sum(x["claims"] for x in m["negative"].values())),
        ),
    ]
    lines = [
        "# Evaluation",
        "",
        "| Metric | " + " | ".join(names) + " |",
        "|---|" + "---|" * len(names),
    ]
    lines += [
        f"| {label} | " + " | ".join(f(metrics[n]) for n in names) + " |"
        for label, f in rows
    ]
    lines += [
        "",
        "Judge–human agreement and time per gene vs. manual lookup: not measured yet (needs the human review step).",
        "",
    ]

    lines += [
        "## Per gene",
        "",
        "| Gene | Kind | " + " | ".join(names) + " |",
        "|---|---|" + "---|" * len(names),
    ]
    for gene, spec in expected.items():
        cells = []
        for n in names:
            m = metrics[n]
            if gene in m["clear"]:
                x = m["clear"][gene]
                cells.append(
                    ("✓ " + ", ".join(x["terms"]))
                    if x["hit"]
                    else "✗ expected terms missing"
                )
            elif gene in m["negative"]:
                x = m["negative"][gene]
                cells.append(
                    f"{'✓' if x['honest'] else '✗'} {x['evidence_level']}, {x['claims']} claims"
                )
            else:
                cells.append("– missing")
        lines.append(f"| {gene} | {spec['kind']} | " + " | ".join(cells) + " |")

    for n in names:
        lines += ["", f"## Failure cases: {n}", ""]
        if not fails[n]:
            lines.append("None.")
            continue
        lines += ["| Gene | Verdict | Claim | Reason |", "|---|---|---|---|"]
        lines += [
            f"| {g} | `{v}` | {_cell(t)} | {_cell(r)} |" for g, v, t, r in fails[n]
        ]
    return "\n".join(lines) + "\n"


def main() -> None:
    """Evaluate every system found in the run folder, write evaluation.md and evaluation.json."""
    ap = argparse.ArgumentParser(
        description="Compare a gencite run with the baseline on the test set"
    )
    ap.add_argument(
        "run",
        type=Path,
        help="run folder of cli.py, with the baseline in <run>/baseline/",
    )
    ap.add_argument(
        "--expected", type=Path, default=Path("test_data/eval_expected.json")
    )
    args = ap.parse_args()

    expected = json.loads(args.expected.read_text(encoding="utf-8"))
    metrics, fails = {}, {}
    for name, sub in SYSTEMS.items():
        folder = args.run / sub
        if not (folder / "verified").is_dir():
            print(f"{name}: no results in {folder}/verified - skipped", file=sys.stderr)
            continue
        verified, records = load_system(folder)
        metrics[name] = evaluate(verified, records, expected)
        fails[name] = failures(verified, expected)
        if metrics[name]["missing"]:
            print(
                f"{name}: no result for {', '.join(metrics[name]['missing'])}",
                file=sys.stderr,
            )
    if not metrics:
        sys.exit(
            "Nothing to evaluate - run python -m gencite and python -m gencite.baseline first."
        )

    md = build_markdown(metrics, fails, expected)
    (args.run / "evaluation.md").write_text(md, encoding="utf-8")
    (args.run / "evaluation.json").write_text(
        json.dumps(
            {"metrics": metrics, "failures": fails}, indent=2, ensure_ascii=False
        ),
        encoding="utf-8",
    )
    print(md)
    print(f"Wrote {args.run / 'evaluation.md'} and evaluation.json")


if __name__ == "__main__":
    main()

"""Step 9: Gene report. Combines verified claims with the gene's evidence into one Markdown report + a terminal summary."""


import argparse
import sys
from datetime import date
from pathlib import Path

from schema import GeneRecord, VerifyResult
from synth_LLM import load_records

MARK = {"supported": "+", "partial": "~", "unsupported": "-", "invalid_id": "X", "unchecked": "?"}
ORDER = ["supported", "partial", "unsupported", "invalid_id", "unchecked"]
DISCLAIMER = ("Claims are LLM summaries of the retrieved evidence. Each claim's status shows whether a second LLM "
              "found it in the cited evidence; claims marked `?` were not checked. "
              "A generated summary is not a validated finding: read the cited sources before using a claim.")


def counts(res: VerifyResult) -> dict[str, int]:
    return {v: sum(c.verdict == v for c in res.claims) for v in ORDER}


def _cell(text: str) -> str:
    """Make text safe for one Markdown table cell."""
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _link(eid: str, record: GeneRecord | None) -> str:
    e = next((e for e in record.evidence if e.id == eid), None) if record else None
    return f"[{eid}]({e.url})" if e and e.url else f"`{eid}`"


def gene_section(res: VerifyResult, record: GeneRecord | None) -> str:
    g = record.gene if record else None
    head = [f"## {res.gene}", ""]
    if g and not g.found:
        head.append("Type: – · Ensembl: – · Evidence: **none** (symbol not resolved)")
    elif g:
        ens = f"[{g.ensembl_id}](https://www.ensembl.org/Homo_sapiens/Gene/Summary?g={g.ensembl_id})" if g.ensembl_id else "–"
        head.append(f"Type: {g.gene_type or 'unknown'} · Ensembl: {ens} · Evidence: **{res.evidence_level}**")
    else:
        head.append(f"Evidence: **{res.evidence_level}** (no GeneRecord found, sources are not linked)")
    if res.note:
        head += ["", f"> {res.note}"]
    head.append("")

    if not res.claims:
        return "\n".join(head + ["No claims.", ""])

    lines = head + ["| # | Status | Claim | Sources | Verifier reason |", "|---|---|---|---|---|"]
    for i, c in enumerate(res.claims, 1):
        src = ", ".join(_link(e, record) for e in c.evidence_ids)
        lines.append(f"| {i} | `{MARK[c.verdict]}` {c.verdict} | {_cell(c.text)} | {src} | {_cell(c.reason)} |")

    if record and record.evidence:
        lines += ["", "<details><summary>Retrieved evidence</summary>", ""]
        for e in record.evidence:
            used = [str(i) for i, c in enumerate(res.claims, 1) if e.id in c.evidence_ids]
            tag = f"cited by claim {', '.join(used)}" if used else "not cited"
            lines.append(f"- {_link(e.id, record)} {_cell(e.title)} ({tag})")
        lines += ["", "</details>"]
    return "\n".join(lines + [""])


def build_report(results: list[VerifyResult], records: dict[str, GeneRecord]) -> str:
    lines = ["# gencite report", "", f"{date.today().isoformat()} · {len(results)} genes", "",
             f"*{DISCLAIMER}*", ""]
    unchecked = sum(counts(r)["unchecked"] for r in results)
    if unchecked:
        lines += [f"**Warning: {unchecked} claims were not checked by the judge (`?`), treat them as unverified.**", ""]
    lines += ["| Gene | Type | Evidence | Claims | + | ~ | - | X | ? |", "|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        rec = records.get(r.gene)
        gtype = (rec.gene.gene_type or "unknown") if rec and rec.gene.found else "not resolved" if rec else "?"
        n = counts(r)
        lines.append(f"| [{r.gene}](#{r.gene.lower()}) | {gtype} | {r.evidence_level} | {len(r.claims)} | "
                     f"{n['supported']} | {n['partial']} | {n['unsupported']} | {n['invalid_id']} | {n['unchecked']} |")
    lines += ["", "Status: `+` supported · `~` partial · `-` unsupported · `X` cited ID not in this gene's evidence"
              " · `?` not checked by the judge", ""]
    return "\n".join(lines + [gene_section(r, records.get(r.gene)) for r in results])


def print_summary(results: list[VerifyResult]) -> None:
    for r in results:
        print(f"\n{r.gene} [{r.evidence_level}]" + (f" {r.note}" if r.note else ""))
        for c in r.claims:
            print(f"  {MARK[c.verdict]} {c.text}  {c.evidence_ids}")
    total = {v: sum(counts(r)[v] for r in results) for v in ORDER}
    n = sum(total.values())
    print(f"\n{len(results)} genes, {n} claims: " + ", ".join(f"{total[v]} {v}" for v in ORDER if total[v]))


def main() -> None:
    ap = argparse.ArgumentParser(description="Gene report: verified claims + linked sources -> Markdown")
    ap.add_argument("verified", type=Path, help="folder with VerifyResult JSONs")
    ap.add_argument("records", type=Path, help="folder with the matching GeneRecord JSONs")
    ap.add_argument("--out", type=Path, default=Path("results/steps/report.md"))
    args = ap.parse_args()

    results = [VerifyResult.model_validate_json(f.read_text(encoding="utf-8"))
               for f in sorted(args.verified.glob("*.json"))]
    if not results:
        sys.exit(f"No VerifyResult JSONs in {args.verified}")
    if not args.records.is_dir():
        sys.exit(f"Records folder not found: {args.records}")
    records = {r.gene.symbol: r for r in load_records([args.records])}
    for r in results:
        if r.gene not in records:
            print(f"{r.gene}: no GeneRecord found in {args.records}, sources are not linked", file=sys.stderr)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(build_report(results, records), encoding="utf-8")
    print_summary(results)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()

"""Step 6: Synthesizer. Reads one gene's evidence and writes short claims, each citing evidence IDs."""


import argparse
import sys
from pathlib import Path

from pydantic import BaseModel, Field

from llm_client import LLMOutputError, llm_json
from schema import Claim, EvidenceLevel, GeneRecord, SynthResult

SYSTEM = """You summarise the biology of one human gene for a scientist.
You get evidence items, each with an ID in square brackets. Write up to 5 short claims on the gene's function and disease relevance.
Rules:
- Use ONLY the given evidence. No background knowledge, no facts that are not in the evidence text.
- Every claim MUST cite at least one evidence ID, copied exactly from the list (without the brackets).
- One fact per claim. Keep the strength of the evidence: association is not causation, a mouse study is not human, one study is not "all".
- If an item is about a different gene or only mentions this gene in passing, do not use it.
- For pseudogenes, readthroughs and ncRNAs: do not describe the parent or partner protein-coding gene as if it were this gene.
Rate the evidence:
- "sufficient": the evidence directly describes this gene's function or disease relevance.
- "limited": only predictions, passing mentions or a single weak item. Write only the claims the evidence allows.
- "none": nothing usable about this gene. Return an empty claims list.
For "limited" and "none", explain in "note" in one sentence what is missing.
Output JSON only:
{"evidence_level": "sufficient|limited|none", "note": "...", "claims": [{"text": "...", "evidence_ids": ["PMID:123"]}]}"""


class LLMOutput(BaseModel):
    evidence_level: EvidenceLevel
    note: str = ""
    claims: list[Claim] = Field(default_factory=list, max_length=6)


def build_prompt(record: GeneRecord) -> str:
    g = record.gene
    lines = ["GENE:", g.symbol, f"Gene type: {g.gene_type or 'unknown'}", "", "EVIDENCE:", ""]
    for e in record.evidence:
        lines.append(f"[{e.id}]")
        if e.title:
            lines.append(e.title)
        lines.append(e.text.strip())
        lines.append("")
    return "\n".join(lines)


def synthesize(record: GeneRecord) -> SynthResult:
    """Claims with evidence_ids. Unresolved gene or no evidence -> no LLM call, no claims."""
    symbol = record.gene.symbol
    if not record.gene.found:
        return SynthResult(gene=symbol, evidence_level="none", note="Gene symbol could not be resolved.")
    if not record.evidence:
        return SynthResult(gene=symbol, evidence_level="none", note="No evidence retrieved for this gene.")
    out = llm_json(build_prompt(record), SYSTEM, LLMOutput, role="synth")
    if out.evidence_level == "none":
        out.claims = []  # keep "none" consistent even if the model still wrote claims
    return SynthResult(gene=symbol, **out.model_dump())


def load_records(paths: list[Path]) -> list[GeneRecord]:
    files = []
    for p in paths:
        files += sorted(p.glob("*.json")) if p.is_dir() else [p]
    return [GeneRecord.model_validate_json(f.read_text(encoding="utf-8")) for f in files]


def main() -> None:
    ap = argparse.ArgumentParser(description="LLM synthesizer: evidence -> cited claims")
    ap.add_argument("inputs", nargs="+", type=Path, help="GeneRecord JSON files or folders")
    ap.add_argument("--out", type=Path, default=Path("output/synth"))
    ap.add_argument("--dry-run", action="store_true", help="print prompts, do not call the LLM")
    args = ap.parse_args()

    records = load_records(args.inputs)
    if args.dry_run:
        for r in records:
            print(f"===== {r.gene.symbol} =====\n{build_prompt(r)}")
        return

    args.out.mkdir(parents=True, exist_ok=True)
    failed = 0
    for r in records:
        try:
            res = synthesize(r)
        except LLMOutputError as err:
            print(f"{r.gene.symbol}: synthesis failed - {err}", file=sys.stderr)
            failed += 1
            continue
        (args.out / f"{r.gene.symbol}.json").write_text(res.model_dump_json(indent=2), encoding="utf-8")
        print(f"\n{res.gene} [{res.evidence_level}] {res.note}")
        for c in res.claims:
            print(f"  - {c.text} {c.evidence_ids}")
    print(f"\nWrote {len(records) - failed} results to {args.out}/" + (f", {failed} failed" if failed else ""))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()

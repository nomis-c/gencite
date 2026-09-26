"""Baseline: the same LLM without retrieval. It writes claims from memory and cites PMIDs it remembers.

    python -m gencite.baseline test_data/eval_genes.txt            # -> results/eval_genes/baseline/
    python -m gencite.baseline test_data/eval_genes.txt --no-judge

The cited PMIDs are fetched from PubMed and become the gene's evidence, then the unchanged verifier runs:
layer 1 marks PMIDs that do not exist as invalid_id, layer 2 judges the real ones with the same judge as gencite.
Output mirrors a cli.py run (synth/, records/, verified/), so evaluate.py reads both the same way.
"""

import argparse
import re
import shutil
import sys
from pathlib import Path

from gencite import cache
from gencite.inputs import parse_gene_list
from gencite.llm_client import llm_json
from gencite.pubmed_retrieval import fetch_pubmed_records
from gencite.schema import GeneInfo, GeneRecord, SynthResult
from gencite.synth_LLM import LLMOutput
from gencite.verify import judge_failures, verify

SYSTEM = """You summarise the biology of one human gene for a scientist.
Write up to 5 short claims on the gene's function and disease relevance, from your own knowledge.
Rules:
- Every claim MUST cite at least one PubMed article that supports it, written as "PMID:<number>".
- One fact per claim. Keep the strength of the evidence: association is not causation, a mouse study is not human, one study is not "all".
- For pseudogenes, readthroughs and ncRNAs: do not describe the parent or partner protein-coding gene as if it were this gene.
Rate what you know:
- "sufficient": the gene's function or disease relevance is well described in the literature.
- "limited": you know little about this gene. Write only the claims you are sure of.
- "none": you know nothing reliable about this gene. Return an empty claims list.
For "limited" and "none", explain in "note" in one sentence what is missing.
Output JSON only:
{"evidence_level": "sufficient|limited|none", "note": "...", "claims": [{"text": "...", "evidence_ids": ["PMID:123"]}]}"""

PMID = re.compile(r"PMID:(\d+)$")
STAGES = ("synth", "records", "verified")


def build_prompt(symbol: str) -> str:
    return f"GENE:\n{symbol}"


def synthesize_baseline(symbol: str) -> SynthResult:
    out = llm_json(build_prompt(symbol), SYSTEM, LLMOutput, role="synth")
    if out.evidence_level == "none":
        out.claims = []
    return SynthResult(gene=symbol, **out.model_dump())


def fetch_cited(synth: SynthResult) -> GeneRecord:
    """Evidence = the cited PMIDs that exist in PubMed. Missing or malformed IDs stay out, so layer 1 flags them."""
    pmids = sorted(
        {
            m.group(1)
            for c in synth.claims
            for i in c.evidence_ids
            if (m := PMID.match(i.strip()))
        }
    )
    evidence = fetch_pubmed_records(pmids) if pmids else []
    return GeneRecord.model_validate(
        {"gene": GeneInfo(symbol=synth.gene).model_dump(), "evidence": evidence}
    )


def _save(folder: Path, name: str, obj) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.json").write_text(
        obj.model_dump_json(indent=2), encoding="utf-8"
    )


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Baseline: same LLM without retrieval, cited PMIDs checked afterwards"
    )
    ap.add_argument("genes", type=Path, help="gene list (one symbol per line)")
    ap.add_argument(
        "--out",
        type=Path,
        help="output folder (default: results/<input name>/baseline)",
    )
    ap.add_argument(
        "--no-judge",
        action="store_true",
        help="skip verifier layer 2 (fewer LLM calls)",
    )
    ap.add_argument(
        "--no-cache",
        action="store_true",
        help="always call the LLM (nothing read or written)",
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="print the prompt, do not call the LLM"
    )
    args = ap.parse_args()
    cache.ENABLED = not args.no_cache

    if not args.genes.is_file():
        sys.exit(f"Input not found: {args.genes}")
    symbols = parse_gene_list(args.genes.read_text(encoding="utf-8"))
    if args.dry_run:
        print(f"===== SYSTEM =====\n{SYSTEM}\n")
        for s in symbols:
            print(f"===== {s} =====\n{build_prompt(s)}")
        return
    out = args.out or Path("results") / args.genes.stem / "baseline"
    for (
        stage
    ) in (
        STAGES
    ):  # drop the last run, so a gene that fails now is missing instead of stale
        shutil.rmtree(out / stage, ignore_errors=True)

    failed = unjudged = 0
    for i, symbol in enumerate(symbols, 1):
        try:
            synth = synthesize_baseline(symbol)
            record = fetch_cited(synth)
            res = verify(synth, record, use_llm=not args.no_judge)
        except (
            Exception
        ) as err:  # LLM or PubMed error: skip this gene, keep the run going
            print(f"[{i}/{len(symbols)}] {symbol}: failed - {err}", file=sys.stderr)
            failed += 1
            continue
        for stage, obj in zip(STAGES, (synth, record, res)):
            _save(out / stage, symbol, obj)
        unjudged += judge_failures(res)
        fake = sum(c.verdict == "invalid_id" for c in res.claims)
        print(
            f"[{i}/{len(symbols)}] {symbol}: {res.evidence_level}, {len(res.claims)} claims, "
            f"{len(record.evidence)} cited PMIDs found in PubMed, {fake} claims with invalid IDs"
        )

    print(
        f"Wrote {len(symbols) - failed} baseline results to {out}/"
        + (f", {failed} genes failed" if failed else "")
    )
    if unjudged:
        print(
            f"{unjudged} claims could not be judged (marked unchecked) - rerun to retry them",
            file=sys.stderr,
        )
    if failed or unjudged:
        sys.exit(1)


if __name__ == "__main__":
    main()

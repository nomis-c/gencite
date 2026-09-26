"""Command line entry point: gene list -> evidence -> claims -> verification -> report.

    python3 cli.py gene_list.txt          # full pipeline (steps 1-9)
    python3 cli.py test_data              # folder of GeneRecord JSONs: skip steps 1-5
    python3 cli.py gene_list.txt --no-judge
"""


import argparse
import sys
from pathlib import Path

import cache
from create_report import MARK, build_report, counts, print_summary
from schema import GeneRecord, SynthResult, VerifyResult
from synth_LLM import load_records, synthesize
from verify import judge_failures, verify


def fetch_records(gene_file: Path) -> list[GeneRecord]:
    """Steps 1-5: parse the list, resolve IDs, collect PubMed + Open Targets evidence."""
    try:  # imported here so the records-folder mode works without the retrieval modules
        from collect_evidence import collect_evidence
        from ids import resolve_gene_id
        from inputs import parse_gene_list
    except ModuleNotFoundError as err:
        sys.exit(f"Retrieval modules missing ({err.name}.py) - run on a GeneRecord folder instead, e.g. test_data/")

    symbols = parse_gene_list(gene_file.read_text(encoding="utf-8"))
    records = []
    for i, symbol in enumerate(symbols, 1):
        try:
            raw = collect_evidence(resolve_gene_id(symbol))
        except Exception as err:  # network / API errors: report and go on with the next gene
            print(f"[{i}/{len(symbols)}] {symbol}: retrieval failed - {err}", file=sys.stderr)
            continue
        for e in raw.get("errors", []):
            print(f"[{i}/{len(symbols)}] {symbol}: {e['source']} - {e['message']}", file=sys.stderr)
        rec = GeneRecord.model_validate(raw)
        print(f"[{i}/{len(symbols)}] {symbol}: {len(rec.evidence)} evidence items")
        records.append(rec)
    return records


def run_gene(record: GeneRecord, use_judge: bool) -> tuple[SynthResult, VerifyResult]:
    """Steps 6-8 for one gene."""
    synth = synthesize(record)
    return synth, verify(synth, record, use_llm=use_judge)


def _save(folder: Path, name: str, obj) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.json").write_text(obj.model_dump_json(indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="gencite: cited, verified gene summaries from a gene list")
    ap.add_argument("input", type=Path, help="gene list (one symbol per line) or folder of GeneRecord JSONs")
    ap.add_argument("--out", type=Path, default=Path("output/run"), help="output folder (default: output/run)")
    ap.add_argument("--no-judge", action="store_true", help="skip verifier layer 2 (fewer LLM calls)")
    ap.add_argument("--no-cache", action="store_true", help="always call the APIs and the LLM (nothing read or written)")
    args = ap.parse_args()
    cache.ENABLED = not args.no_cache

    if not args.input.exists():
        sys.exit(f"Input not found: {args.input}")
    if args.input.is_dir():
        records = load_records([args.input])
    else:
        records = fetch_records(args.input)
        for r in records:
            _save(args.out / "records", r.gene.symbol, r)
    if not records:
        sys.exit("No genes to process.")

    results, failed, unjudged = [], 0, 0
    for i, rec in enumerate(records, 1):
        symbol = rec.gene.symbol
        try:
            synth, res = run_gene(rec, use_judge=not args.no_judge)
        except Exception as err:  # synthesis failed (LLM error, rate limit): skip this gene, keep the run going
            print(f"[{i}/{len(records)}] {symbol}: failed - {err}", file=sys.stderr)
            failed += 1
            continue
        _save(args.out / "synth", symbol, synth)
        _save(args.out / "verified", symbol, res)
        unjudged += judge_failures(res)
        n = counts(res)
        marks = " ".join(f"{n[v]}{MARK[v]}" for v in n if n[v])
        print(f"[{i}/{len(records)}] {symbol}: {res.evidence_level}, {len(res.claims)} claims" + (f" ({marks})" if marks else ""))
        results.append(res)

    if results:
        report = args.out / "report.md"
        report.write_text(build_report(results, {r.gene.symbol: r for r in records}), encoding="utf-8")
        print_summary(results)
        print(f"Wrote {report}" + (f", {failed} genes failed" if failed else ""))
    if cache.ENABLED:
        print(f"Cache: {cache.stats['hits']} hits, {cache.stats['misses']} new calls ({cache.CACHE_DIR})")
    if unjudged:
        print(f"{unjudged} claims could not be judged (marked unchecked) - rerun to retry them", file=sys.stderr)
    if failed or unjudged:
        sys.exit(1)


if __name__ == "__main__":
    main()

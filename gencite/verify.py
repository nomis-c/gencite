"""Steps 7+8: Verifier. Layer 1 checks cited IDs in code, layer 2 lets an LLM judge each claim against its cited evidence."""

import argparse
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from gencite.llm_client import llm_json
from gencite.schema import (
    Claim,
    ClaimCheck,
    Evidence,
    GeneRecord,
    SynthResult,
    VerifyResult,
)
from gencite.synth_LLM import load_records

SYSTEM = """You check one claim about a human gene against the evidence it cites.
Judge ONLY from the given evidence text. Ignore your own background knowledge, even if the claim is true in general.
- "supported": every part of the claim is stated in the evidence, with the same strength.
- "partial": the core is in the evidence, but the claim adds details, overstates it (association -> causation, mouse -> human, one study -> general fact) or mixes up genes.
- "unsupported": the evidence does not say this, contradicts it, or is about a different gene.
Output JSON only:
{"verdict": "supported|partial|unsupported", "reason": "one short sentence"}"""


JUDGE_FAILED = "Judge failed: "


class Judgement(BaseModel):
    verdict: Literal["supported", "partial", "unsupported"]
    reason: str


# Layer 1: deterministic


def check_ids(claim: Claim, evidence_ids: set[str]) -> list[str]:
    """Cited IDs that are not in this gene's evidence list (hallucinated or copied wrong)."""
    return [i for i in claim.evidence_ids if i not in evidence_ids]


# Layer 2: LLM judge


def build_prompt(claim: Claim, record: GeneRecord, cited: list[Evidence]) -> str:
    g = record.gene
    lines = [
        "GENE:",
        g.symbol,
        f"Gene type: {g.gene_type or 'unknown'}",
        "",
        "CLAIM:",
        claim.text,
        "",
        "CITED EVIDENCE:",
        "",
    ]
    for e in cited:
        lines.append(f"[{e.id}]")
        if e.title:
            lines.append(e.title)
        lines.append(e.text.strip())
        lines.append("")
    return "\n".join(lines)


def judge_claim(claim: Claim, record: GeneRecord, cited: list[Evidence]) -> Judgement:
    return llm_json(build_prompt(claim, record, cited), SYSTEM, Judgement, role="judge")


def verify(
    synth: SynthResult, record: GeneRecord, use_llm: bool = True
) -> VerifyResult:
    """Layer 1 for every claim. Claims with invalid IDs get "invalid_id" and are not sent to the judge.
    A failed judge call only marks that claim "unchecked", the other claims are still judged.
    """
    by_id = {e.id: e for e in record.evidence}
    checks = []
    for c in synth.claims:
        invalid = check_ids(c, set(by_id))
        if invalid:
            checks.append(
                ClaimCheck(
                    **c.model_dump(),
                    invalid_ids=invalid,
                    verdict="invalid_id",
                    reason=f"Cited ID not in evidence: {', '.join(invalid)}",
                )
            )
            continue
        if not use_llm:
            checks.append(
                ClaimCheck(
                    **c.model_dump(),
                    verdict="unchecked",
                    reason="Layer 2 skipped (--no-llm).",
                )
            )
            continue
        try:
            j = judge_claim(c, record, [by_id[i] for i in c.evidence_ids])
        except (
            Exception
        ) as err:  # bad JSON, rate limit, network, missing key: not cached, so a rerun retries it
            checks.append(
                ClaimCheck(
                    **c.model_dump(),
                    verdict="unchecked",
                    reason=f"{JUDGE_FAILED}{type(err).__name__}: {str(err)[:200]}",
                )
            )
            continue
        checks.append(ClaimCheck(**c.model_dump(), verdict=j.verdict, reason=j.reason))
    return VerifyResult(
        gene=synth.gene,
        evidence_level=synth.evidence_level,
        note=synth.note,
        claims=checks,
    )


def judge_failures(res: VerifyResult) -> int:
    return sum(c.reason.startswith(JUDGE_FAILED) for c in res.claims)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Verifier: layer 1 (cited IDs exist) + layer 2 (LLM judge)"
    )
    ap.add_argument("synth", type=Path, help="folder with SynthResult JSONs")
    ap.add_argument(
        "records", type=Path, help="folder with the matching GeneRecord JSONs"
    )
    ap.add_argument("--out", type=Path, default=Path("results/steps/verified"))
    ap.add_argument("--no-llm", action="store_true", help="run layer 1 only")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="print judge prompts, do not call the LLM",
    )
    args = ap.parse_args()

    records = {r.gene.symbol: r for r in load_records([args.records])}
    synths = [
        SynthResult.model_validate_json(f.read_text(encoding="utf-8"))
        for f in sorted(args.synth.glob("*.json"))
    ]

    if args.dry_run:
        for s in synths:
            if s.gene not in records:
                print(
                    f"{s.gene}: no GeneRecord found in {args.records}", file=sys.stderr
                )
                continue
            r = records[s.gene]
            by_id = {e.id: e for e in r.evidence}
            for c in s.claims:
                if not check_ids(c, set(by_id)):
                    print(
                        f"===== {s.gene} =====\n{build_prompt(c, r, [by_id[i] for i in c.evidence_ids])}"
                    )
        return

    args.out.mkdir(parents=True, exist_ok=True)
    failed = unjudged = 0
    for s in synths:
        if s.gene not in records:
            print(f"{s.gene}: no GeneRecord found in {args.records}", file=sys.stderr)
            failed += 1
            continue
        res = verify(s, records[s.gene], use_llm=not args.no_llm)
        unjudged += judge_failures(res)
        (args.out / f"{res.gene}.json").write_text(
            res.model_dump_json(indent=2), encoding="utf-8"
        )
        print(f"\n{res.gene} [{res.evidence_level}]")
        for c in res.claims:
            print(f"  [{c.verdict}] {c.text}\n      -> {c.reason}")
    print(
        f"\nWrote {len(synths) - failed} results to {args.out}/"
        + (f", {failed} failed" if failed else "")
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

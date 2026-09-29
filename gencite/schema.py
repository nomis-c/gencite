"""Data shapes shared by every pipeline stage."""

from typing import Literal, Optional

from pydantic import BaseModel, Field

# Any retrieval module name (pubmed, open_targets, human_protein_atlas, ...). Kept open on purpose:
# steps 6-9 only use id/title/text/url, so a new source needs no change downstream.
EvidenceSource = str
EvidenceLevel = Literal["sufficient", "limited", "none"]


# 1st part: IDs + evidence


class GeneInfo(BaseModel):
    """Resolved IDs of one gene (step 2). found=False: symbol unknown, nothing is retrieved."""

    symbol: str
    ensembl_id: Optional[str] = None
    entrez_id: Optional[str] = None
    gene_type: Optional[str] = None  # protein-coding | ncRNA | pseudo | readthrough ...
    found: bool = True


class Evidence(BaseModel):
    """One retrieved item. Claims cite its id, the report links its url."""

    id: str  # PMID:12345678 | OT:function:IRGM | OT:disease:IRGM:MONDO_...
    source: EvidenceSource
    title: str = ""
    text: str = ""
    url: str = ""


class GeneRecord(BaseModel):
    """Output of collect_evidence.py, input of the synthesizer."""

    gene: GeneInfo
    evidence: list[Evidence] = Field(default_factory=list)


# 2nd part: synthesis + verification


class Claim(BaseModel):
    """One short statement about the gene, with the evidence IDs it is based on."""

    text: str
    evidence_ids: list[str] = Field(
        min_length=1
    )  # a claim without a citation is rejected


class SynthResult(BaseModel):
    """Output of synth_LLM.py, input of verify.py."""

    gene: str
    evidence_level: EvidenceLevel
    note: str = ""  # why evidence is limited/none, e.g. "gene not resolved"
    claims: list[Claim] = Field(default_factory=list)


Verdict = Literal[
    "supported", "partial", "unsupported", "invalid_id", "unchecked"
]  # unchecked = layer 2 skipped


class ClaimCheck(BaseModel):
    """A claim plus the verifier's result."""

    text: str
    evidence_ids: list[str]
    invalid_ids: list[str] = Field(
        default_factory=list
    )  # layer 1: cited IDs not in this gene's evidence
    verdict: Verdict
    reason: str = ""  # layer 2: one-line judge reason


class VerifyResult(BaseModel):
    """Output of verify.py, input of create_report.py."""

    gene: str
    evidence_level: EvidenceLevel
    note: str = ""
    claims: list[ClaimCheck] = Field(default_factory=list)

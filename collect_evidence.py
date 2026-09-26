from pubmed_retrieval import retrieve_pubmed_evidence
from opentargets import retrieve_open_targets_evidence
from hpa_retrieval import retrieve_hpa_evidence
from amass_retrieval import retrieve_amass_evidence


DEFAULT_EVIDENCE_SOURCES = frozenset({"pubmed", "open_targets", "human_protein_atlas", "amass"})

Sources = set[str] | frozenset[str] | None


def _normalize_enabled_sources(enabled_sources: Sources) -> set[str]:
    """
    Validate and normalize the requested evidence sources.

    If no source selection is provided, all available evidence
    sources are enabled. This preserves the existing CLI behaviour.
    """
    if enabled_sources is None:
        return set(DEFAULT_EVIDENCE_SOURCES)

    enabled = set(enabled_sources)
    unknown = enabled - DEFAULT_EVIDENCE_SOURCES
    if unknown:
        raise ValueError(
            f"Unknown evidence source{'s' if len(unknown) != 1 else ''}: " + ", ".join(sorted(unknown))
        )
    return enabled


def _normalize_publication_url(item: dict) -> str | None:
    """
    Return a normalized publication URL for literature evidence.

    Only publication-specific URLs are used for cross-source
    deduplication.

    Generic provider URLs such as the AMASS platform homepage must
    not be treated as duplicate evidence.
    """
    source = item.get("source")
    url = (item.get("url") or "").strip()
    if not url:
        return None

    # PubMed and AMASS BiomedCore can represent the same
    # underlying publication using different evidence IDs.
    if source not in {"pubmed", "amass_biomedcore"}:
        return None

    normalized = url.rstrip("/").lower()
    if "pubmed.ncbi.nlm.nih.gov/" in normalized or "doi.org/" in normalized:
        return normalized
    return None


def _deduplicate_evidence(evidence: list[dict]) -> list[dict]:
    """
    Remove duplicate evidence while preserving order.

    Evidence is considered duplicate when:
    - its evidence ID has already been seen, or
    - PubMed and AMASS BiomedCore refer to the same underlying
      publication URL.

    Non-literature evidence is not deduplicated merely because
    several records share a generic provider URL.
    """
    seen_ids = set()
    seen_publication_urls = set()
    unique_evidence = []

    for item in evidence:
        evidence_id = item.get("id")
        publication_url = _normalize_publication_url(item)

        if evidence_id and evidence_id in seen_ids:
            continue
        if publication_url and publication_url in seen_publication_urls:
            continue

        if evidence_id:
            seen_ids.add(evidence_id)
        if publication_url:
            seen_publication_urls.add(publication_url)
        unique_evidence.append(item)

    return unique_evidence


def _count_sources(evidence: list[dict]) -> dict:
    """
    Count evidence records after final deduplication.

    AMASS GeneCore and BiomedCore records are grouped together under
    the user-facing 'amass' source count.
    """
    counts = {"pubmed": 0, "open_targets": 0, "human_protein_atlas": 0, "amass": 0}

    for item in evidence:
        source = item.get("source")
        if source in ("pubmed", "open_targets", "human_protein_atlas"):
            counts[source] += 1
        elif isinstance(source, str) and source.startswith("amass"):
            counts["amass"] += 1

    return counts


def collect_evidence(
    gene_info: dict,
    max_pubmed_results: int = 5,
    max_diseases: int = 5,
    max_amass_biomed_results: int = 3,
    enabled_sources: Sources = None,
) -> dict:
    """
    Collect evidence for one resolved gene from selected sources.

    If enabled_sources is None, all available sources are queried.

    Partial results are preserved if one evidence source fails.
    Errors are recorded instead of silently discarded.
    """
    enabled_sources = _normalize_enabled_sources(enabled_sources)

    record = {
        "gene": gene_info,
        "evidence": [],
        "errors": [],
        "source_counts": {"pubmed": 0, "open_targets": 0, "human_protein_atlas": 0, "amass": 0},
        "evidence_count": 0,
    }

    # If the gene could not be resolved,
    # there is nothing useful to query.
    if not gene_info.get("found"):
        record["errors"].append({"source": "gene_resolution", "message": "Gene could not be resolved."})
        return record

    gene_symbol = gene_info.get("symbol")
    gene_name = gene_info.get("name")
    ensembl_id = gene_info.get("ensembl_id")
    entrez_id = gene_info.get("entrez_id")

    def add(source: str, retrieve, missing: str | None = None) -> None:
        """Run one retrieval; record its error instead of stopping the other sources."""
        if source not in enabled_sources:
            return
        if missing:
            record["errors"].append({"source": source, "message": missing})
            return
        try:
            record["evidence"].extend(retrieve())
        except Exception as exc:
            record["errors"].append({"source": source, "message": str(exc)})

    no_ensembl = None if ensembl_id else "No Ensembl ID available for this gene."

    add("pubmed", lambda: retrieve_pubmed_evidence(
        gene_symbol=gene_symbol, gene_name=gene_name, entrez_id=entrez_id, max_results=max_pubmed_results))
    add("open_targets", lambda: retrieve_open_targets_evidence(ensembl_id, max_diseases=max_diseases),
        missing=no_ensembl)
    add("human_protein_atlas", lambda: retrieve_hpa_evidence(ensembl_id), missing=no_ensembl)
    add("amass", lambda: retrieve_amass_evidence(
        gene_symbol=gene_symbol, ensembl_id=ensembl_id, max_biomed_results=max_amass_biomed_results),
        missing=None if gene_symbol else "No gene symbol available for this gene.")

    record["evidence"] = _deduplicate_evidence(record["evidence"])
    record["source_counts"] = _count_sources(record["evidence"])
    record["evidence_count"] = len(record["evidence"])
    return record


def collect_evidence_for_genes(
    gene_infos: list[dict],
    max_pubmed_results: int = 5,
    max_diseases: int = 5,
    max_amass_biomed_results: int = 3,
    enabled_sources: Sources = None,
) -> list[dict]:
    """
    Collect evidence for multiple resolved genes.

    If enabled_sources is None, all available sources are queried.
    """
    return [
        collect_evidence(
            gene_info,
            max_pubmed_results=max_pubmed_results,
            max_diseases=max_diseases,
            max_amass_biomed_results=max_amass_biomed_results,
            enabled_sources=enabled_sources,
        )
        for gene_info in gene_infos
    ]

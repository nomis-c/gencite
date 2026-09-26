from pubmed_retrieval import (
    retrieve_pubmed_evidence,
)
from opentargets import (
    retrieve_open_targets_evidence,
)
from hpa_retrieval import (
    retrieve_hpa_evidence,
)
from amass_retrieval import (
    retrieve_amass_evidence,
)


DEFAULT_EVIDENCE_SOURCES = frozenset({
    "pubmed",
    "open_targets",
    "human_protein_atlas",
    "amass",
})


def _normalize_enabled_sources(
    enabled_sources: (
        set[str]
        | frozenset[str]
        | None
    ),
) -> set[str]:
    """
    Validate and normalize the requested evidence sources.

    If no source selection is provided, all available evidence
    sources are enabled. This preserves the existing CLI behaviour.
    """

    if enabled_sources is None:
        return set(
            DEFAULT_EVIDENCE_SOURCES
        )

    enabled = set(
        enabled_sources
    )

    unknown = (
        enabled
        - DEFAULT_EVIDENCE_SOURCES
    )

    if unknown:
        raise ValueError(
            (
                "Unknown evidence source"
                f"{'s' if len(unknown) != 1 else ''}: "
                + ", ".join(
                    sorted(unknown)
                )
            )
        )

    return enabled


def _normalize_publication_url(
    item: dict,
) -> str | None:
    """
    Return a normalized publication URL for literature evidence.

    Only publication-specific URLs are used for cross-source
    deduplication.

    Generic provider URLs such as the AMASS platform homepage must
    not be treated as duplicate evidence.
    """

    source = item.get("source")
    url = (
        item.get("url") or ""
    ).strip()

    if not url:
        return None

    # PubMed and AMASS BiomedCore can represent the same
    # underlying publication using different evidence IDs.
    if source not in {
        "pubmed",
        "amass_biomedcore",
    }:
        return None

    normalized = (
        url.rstrip("/").lower()
    )

    if (
        "pubmed.ncbi.nlm.nih.gov/"
        in normalized
        or "doi.org/" in normalized
    ):
        return normalized

    return None


def _deduplicate_evidence(
    evidence: list[dict],
) -> list[dict]:
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

        publication_url = (
            _normalize_publication_url(
                item
            )
        )

        if (
            evidence_id
            and evidence_id in seen_ids
        ):
            continue

        if (
            publication_url
            and publication_url
            in seen_publication_urls
        ):
            continue

        if evidence_id:
            seen_ids.add(
                evidence_id
            )

        if publication_url:
            seen_publication_urls.add(
                publication_url
            )

        unique_evidence.append(
            item
        )

    return unique_evidence


def _count_sources(
    evidence: list[dict],
) -> dict:
    """
    Count evidence records after final deduplication.

    AMASS GeneCore and BiomedCore records are grouped together under
    the user-facing 'amass' source count.
    """

    counts = {
        "pubmed": 0,
        "open_targets": 0,
        "human_protein_atlas": 0,
        "amass": 0,
    }

    for item in evidence:
        source = item.get(
            "source"
        )

        if source == "pubmed":
            counts[
                "pubmed"
            ] += 1

        elif source == "open_targets":
            counts[
                "open_targets"
            ] += 1

        elif (
            source
            == "human_protein_atlas"
        ):
            counts[
                "human_protein_atlas"
            ] += 1

        elif (
            isinstance(
                source,
                str,
            )
            and source.startswith(
                "amass"
            )
        ):
            counts[
                "amass"
            ] += 1

    return counts


def collect_evidence(
    gene_info: dict,
    max_pubmed_results: int = 5,
    max_diseases: int = 5,
    max_amass_biomed_results: int = 3,
    enabled_sources: (
        set[str]
        | frozenset[str]
        | None
    ) = None,
) -> dict:
    """
    Collect evidence for one resolved gene from selected sources.

    If enabled_sources is None, all available sources are queried.

    Partial results are preserved if one evidence source fails.
    Errors are recorded instead of silently discarded.
    """

    enabled_sources = (
        _normalize_enabled_sources(
            enabled_sources
        )
    )

    record = {
        "gene": gene_info,
        "evidence": [],
        "errors": [],
        "source_counts": {
            "pubmed": 0,
            "open_targets": 0,
            "human_protein_atlas": 0,
            "amass": 0,
        },
        "evidence_count": 0,
    }

    # If the gene could not be resolved,
    # there is nothing useful to query.
    if not gene_info.get("found"):
        record["errors"].append({
            "source": "gene_resolution",
            "message": (
                "Gene could not be resolved."
            ),
        })

        return record

    gene_symbol = gene_info.get(
        "symbol"
    )

    gene_name = gene_info.get(
        "name"
    )

    ensembl_id = gene_info.get(
        "ensembl_id"
    )

    entrez_id = gene_info.get(
        "entrez_id"
    )

    # -------------------------
    # PubMed evidence
    # -------------------------

    if "pubmed" in enabled_sources:
        try:
            pubmed_evidence = (
                retrieve_pubmed_evidence(
                    gene_symbol=gene_symbol,
                    gene_name=gene_name,
                    entrez_id=entrez_id,
                    max_results=(
                        max_pubmed_results
                    ),
                )
            )

            record["evidence"].extend(
                pubmed_evidence
            )

        except Exception as exc:
            record[
                "errors"
            ].append({
                "source": "pubmed",
                "message": str(exc),
            })

    # -------------------------
    # Open Targets evidence
    # -------------------------

    if (
        "open_targets"
        in enabled_sources
    ):
        if ensembl_id:
            try:
                open_targets_evidence = (
                    retrieve_open_targets_evidence(
                        ensembl_id,
                        max_diseases=(
                            max_diseases
                        ),
                    )
                )

                record[
                    "evidence"
                ].extend(
                    open_targets_evidence
                )

            except Exception as exc:
                record[
                    "errors"
                ].append({
                    "source": (
                        "open_targets"
                    ),
                    "message": str(exc),
                })

        else:
            record[
                "errors"
            ].append({
                "source": (
                    "open_targets"
                ),
                "message": (
                    "No Ensembl ID available "
                    "for this gene."
                ),
            })

    # -------------------------
    # Human Protein Atlas evidence
    # -------------------------

    if (
        "human_protein_atlas"
        in enabled_sources
    ):
        if ensembl_id:
            try:
                hpa_evidence = (
                    retrieve_hpa_evidence(
                        ensembl_id
                    )
                )

                record[
                    "evidence"
                ].extend(
                    hpa_evidence
                )

            except Exception as exc:
                record[
                    "errors"
                ].append({
                    "source": (
                        "human_protein_atlas"
                    ),
                    "message": str(exc),
                })

        else:
            record[
                "errors"
            ].append({
                "source": (
                    "human_protein_atlas"
                ),
                "message": (
                    "No Ensembl ID available "
                    "for this gene."
                ),
            })

    # -------------------------
    # AMASS evidence
    # -------------------------

    if "amass" in enabled_sources:
        if gene_symbol:
            try:
                amass_evidence = (
                    retrieve_amass_evidence(
                        gene_symbol=(
                            gene_symbol
                        ),
                        ensembl_id=(
                            ensembl_id
                        ),
                        max_biomed_results=(
                            max_amass_biomed_results
                        ),
                    )
                )

                record[
                    "evidence"
                ].extend(
                    amass_evidence
                )

            except Exception as exc:
                record[
                    "errors"
                ].append({
                    "source": "amass",
                    "message": str(exc),
                })

        else:
            record[
                "errors"
            ].append({
                "source": "amass",
                "message": (
                    "No gene symbol available "
                    "for this gene."
                ),
            })

    # -------------------------
    # Final cleanup
    # -------------------------

    record["evidence"] = (
        _deduplicate_evidence(
            record["evidence"]
        )
    )

    record["source_counts"] = (
        _count_sources(
            record["evidence"]
        )
    )

    record["evidence_count"] = len(
        record["evidence"]
    )

    return record


def collect_evidence_for_genes(
    gene_infos: list[dict],
    max_pubmed_results: int = 5,
    max_diseases: int = 5,
    max_amass_biomed_results: int = 3,
    enabled_sources: (
        set[str]
        | frozenset[str]
        | None
    ) = None,
) -> list[dict]:
    """
    Collect evidence for multiple resolved genes.

    If enabled_sources is None, all available sources are queried.
    """

    return [
        collect_evidence(
            gene_info,
            max_pubmed_results=(
                max_pubmed_results
            ),
            max_diseases=(
                max_diseases
            ),
            max_amass_biomed_results=(
                max_amass_biomed_results
            ),
            enabled_sources=(
                enabled_sources
            ),
        )
        for gene_info
        in gene_infos
    ]
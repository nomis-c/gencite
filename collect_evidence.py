from pubmed_retrieval import retrieve_pubmed_evidence
from opentargets import retrieve_open_targets_evidence
from hpa_retrieval import retrieve_hpa_evidence


def _deduplicate_evidence(evidence: list[dict]) -> list[dict]:
    """
    Remove duplicate evidence records based on their unique evidence ID,
    while preserving the original order.
    """
    seen_ids = set()
    unique_evidence = []

    for item in evidence:
        evidence_id = item.get("id")

        if not evidence_id:
            continue

        if evidence_id not in seen_ids:
            seen_ids.add(evidence_id)
            unique_evidence.append(item)

    return unique_evidence


def collect_evidence(
    gene_info: dict,
    max_pubmed_results: int = 5,
    max_diseases: int = 5,
) -> dict:
    """
    Collect evidence for one resolved gene from all available sources.

    Partial results are preserved if one evidence source fails.
    Errors are recorded instead of silently discarded.
    """

    record = {
        "gene": gene_info,
        "evidence": [],
        "errors": [],
        "source_counts": {
            "pubmed": 0,
            "open_targets": 0,
            "human_protein_atlas": 0,
        },
        "evidence_count": 0,
    }

    # If the gene could not be resolved, there is nothing useful to query.
    if not gene_info.get("found"):
        record["errors"].append({
            "source": "gene_resolution",
            "message": "Gene could not be resolved.",
        })
        return record

    gene_symbol = gene_info.get("symbol")
    ensembl_id = gene_info.get("ensembl_id")

    # -------------------------
    # PubMed evidence
    # -------------------------
    try:
        pubmed_evidence = retrieve_pubmed_evidence(
            gene_symbol,
            max_results=max_pubmed_results,
        )

        record["evidence"].extend(pubmed_evidence)
        record["source_counts"]["pubmed"] = len(pubmed_evidence)

    except Exception as exc:
        record["errors"].append({
            "source": "pubmed",
            "message": str(exc),
        })

    # -------------------------
    # Open Targets evidence
    # -------------------------
    if ensembl_id:
        try:
            open_targets_evidence = retrieve_open_targets_evidence(
                ensembl_id,
                max_diseases=max_diseases,
            )

            record["evidence"].extend(open_targets_evidence)
            record["source_counts"]["open_targets"] = len(
                open_targets_evidence
            )

        except Exception as exc:
            record["errors"].append({
                "source": "open_targets",
                "message": str(exc),
            })

    else:
        record["errors"].append({
            "source": "open_targets",
            "message": "No Ensembl ID available for this gene.",
        })

    # -------------------------
    # Human Protein Atlas evidence
    # -------------------------
    if ensembl_id:
        try:
            hpa_evidence = retrieve_hpa_evidence(ensembl_id)

            record["evidence"].extend(hpa_evidence)
            record["source_counts"]["human_protein_atlas"] = len(
                hpa_evidence
            )

        except Exception as exc:
            record["errors"].append({
                "source": "human_protein_atlas",
                "message": str(exc),
            })

    else:
        record["errors"].append({
            "source": "human_protein_atlas",
            "message": "No Ensembl ID available for this gene.",
        })

    # -------------------------
    # Final cleanup
    # -------------------------
    record["evidence"] = _deduplicate_evidence(record["evidence"])
    record["evidence_count"] = len(record["evidence"])

    return record


def collect_evidence_for_genes(
    gene_infos: list[dict],
    max_pubmed_results: int = 5,
    max_diseases: int = 5,
) -> list[dict]:
    """
    Collect evidence for multiple resolved genes.
    """

    return [
        collect_evidence(
            gene_info,
            max_pubmed_results=max_pubmed_results,
            max_diseases=max_diseases,
        )
        for gene_info in gene_infos
    ]
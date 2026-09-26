import requests

HPA_BASE_URL = "https://www.proteinatlas.org"


def retrieve_hpa_evidence(ensembl_id: str) -> list[dict]:
    """
    Retrieve Human Protein Atlas information for one human gene
    and normalize it into GenCite evidence records.

    If HPA has no entry for the Ensembl ID, return an empty list
    instead of treating the missing record as a pipeline error.
    """

    url = f"{HPA_BASE_URL}/{ensembl_id}.json"

    response = requests.get(url, timeout=15)

    # A valid human Ensembl gene may simply not have an HPA entry.
    # Treat this as "no HPA evidence available", not as an error.
    if response.status_code == 404:
        return []

    response.raise_for_status()

    data = response.json()

    # HPA may return either one object or a single-item list.
    if isinstance(data, list):
        if not data:
            return []
        data = data[0]

    if not isinstance(data, dict):
        return []

    gene_symbol = data.get("Gene") or data.get("Gene name") or ensembl_id

    evidence = []

    # -------------------------
    # Tissue-expression summary
    # -------------------------
    tissue_specificity = data.get("RNA tissue specificity")
    tissue_distribution = data.get("RNA tissue distribution")
    tissue_specific_ntpm = data.get("RNA tissue specific nTPM")

    tissue_parts = []

    if tissue_specificity:
        tissue_parts.append(f"RNA tissue specificity: {tissue_specificity}")

    if tissue_distribution:
        tissue_parts.append(f"RNA tissue distribution: {tissue_distribution}")

    if tissue_specific_ntpm:
        if isinstance(tissue_specific_ntpm, dict):
            formatted_tissues = ", ".join(
                f"{tissue} = {value} nTPM"
                for tissue, value in tissue_specific_ntpm.items()
            )
            tissue_parts.append(f"RNA tissue-specific expression: {formatted_tissues}")
        else:
            tissue_parts.append(
                f"RNA tissue-specific expression: {tissue_specific_ntpm}"
            )

    if tissue_parts:
        evidence.append(
            {
                "id": f"HPA:tissue:{ensembl_id}",
                "source": "human_protein_atlas",
                "title": f"Tissue expression for {gene_symbol}",
                "text": ". ".join(tissue_parts) + ".",
                "url": f"{HPA_BASE_URL}/{ensembl_id}",
            }
        )

    # -------------------------
    # Single-cell summary
    # -------------------------
    cell_specificity = data.get("RNA single cell type specificity")
    cell_distribution = data.get("RNA single cell type distribution")

    cell_parts = []

    if cell_specificity:
        cell_parts.append(f"Single-cell type specificity: {cell_specificity}")

    if cell_distribution:
        cell_parts.append(f"Single-cell type distribution: {cell_distribution}")

    if cell_parts:
        evidence.append(
            {
                "id": f"HPA:celltype:{ensembl_id}",
                "source": "human_protein_atlas",
                "title": f"Cell-type expression for {gene_symbol}",
                "text": ". ".join(cell_parts) + ".",
                "url": f"{HPA_BASE_URL}/{ensembl_id}",
            }
        )

    # -------------------------
    # Biological annotation
    # -------------------------
    biological_process = data.get("Biological process")
    molecular_function = data.get("Molecular function")
    disease_involvement = data.get("Disease involvement")

    annotation_parts = []

    if biological_process:
        annotation_parts.append(f"Biological process: {biological_process}")

    if molecular_function:
        annotation_parts.append(f"Molecular function: {molecular_function}")

    if disease_involvement:
        annotation_parts.append(f"Disease involvement: {disease_involvement}")

    if annotation_parts:
        evidence.append(
            {
                "id": f"HPA:annotation:{ensembl_id}",
                "source": "human_protein_atlas",
                "title": f"HPA annotation for {gene_symbol}",
                "text": ". ".join(annotation_parts) + ".",
                "url": f"{HPA_BASE_URL}/{ensembl_id}",
            }
        )

    return evidence

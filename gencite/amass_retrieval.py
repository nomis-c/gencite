"""Optional source: AMASS GeneCore (gene summary, metadata, UniProt protein function) and
BiomedCore (up to a few relevant publications). Needs AMASS_API_KEY in .env.

GeneCore is looked up by Ensembl ID first, then by symbol. BiomedCore is supplementary:
if it times out or fails, the GeneCore evidence is still kept.
Evidence IDs: "AMASS:gene|metadata|protein|biomed:<AMASS ID>".
"""

import os
import re

import requests
from dotenv import load_dotenv

load_dotenv()

AMASS_BASE_URL = "https://api.amass.tech/api/v1"
AMASS_API_KEY = os.getenv("AMASS_API_KEY")

GENECORE_TIMEOUT = 15
BIOMEDCORE_TIMEOUT = 15


def _get_headers() -> dict:
    """
    Build authentication headers for AMASS.
    """
    if not AMASS_API_KEY:
        raise RuntimeError(
            "AMASS_API_KEY is not set. " "Add it to the local .env file."
        )

    return {
        "Authorization": f"Bearer {AMASS_API_KEY}",
        "Content-Type": "application/json",
    }


def _unwrap_data(payload):
    """
    AMASS responses may either expose the useful object directly
    or wrap it under a top-level 'data' key.
    """
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]

    return payload


def _lookup_genecore_amass_id(
    gene_symbol: str,
    ensembl_id: str | None = None,
) -> str | None:
    """
    Resolve a public gene identifier to a canonical AMASS GeneCore ID.

    Prefer Ensembl because GenCite already resolves Ensembl IDs.
    Fall back to the gene symbol if necessary.
    """

    url = f"{AMASS_BASE_URL}/cores/genecore/records/lookup"

    lookup_items = []

    if ensembl_id:
        lookup_items.append({"ensemblGeneId": ensembl_id})

    if gene_symbol:
        lookup_items.append({"symbol": gene_symbol})

    for item in lookup_items:
        try:
            response = requests.post(
                url,
                headers=_get_headers(),
                json={"items": [item]},
                timeout=GENECORE_TIMEOUT,
            )

            response.raise_for_status()

        except requests.exceptions.Timeout:
            continue

        payload = _unwrap_data(response.json())

        # The lookup API returns one result per submitted item.
        if isinstance(payload, list) and payload:
            result = payload[0]

        elif isinstance(payload, dict):
            result = payload

        else:
            continue

        amass_ids = result.get("amassIds") or []

        if amass_ids:
            return amass_ids[0]

    return None


def _fetch_genecore_record(
    amass_id: str,
) -> dict | None:
    """
    Fetch one exact GeneCore record by AMASS ID.
    """

    url = f"{AMASS_BASE_URL}/cores/genecore/" f"records/{amass_id}"

    try:
        response = requests.get(
            url,
            headers=_get_headers(),
            params={"include": "protein"},
            timeout=GENECORE_TIMEOUT,
        )

        if response.status_code == 404:
            return None

        response.raise_for_status()

    except requests.exceptions.Timeout:
        return None

    payload = _unwrap_data(response.json())

    if isinstance(payload, dict):
        return payload

    return None


def get_amass_gene_record(
    gene_symbol: str,
    ensembl_id: str | None = None,
) -> dict | None:
    """
    Resolve and retrieve the exact GeneCore record for one gene.
    """

    amass_id = _lookup_genecore_amass_id(
        gene_symbol=gene_symbol,
        ensembl_id=ensembl_id,
    )

    if not amass_id:
        return None

    return _fetch_genecore_record(amass_id)


def _gene_record_to_evidence(
    record: dict,
    fallback_symbol: str,
) -> list[dict]:
    """
    Convert a GeneCore record into GenCite evidence records.
    """

    amass_id = record.get("amassId")

    if not amass_id:
        return []

    symbol = record.get("symbol") or fallback_symbol
    evidence = []

    # -------------------------
    # Functional summary
    # -------------------------
    summary = record.get("summary")

    if summary:
        evidence.append(
            {
                "id": f"AMASS:gene:{amass_id}",
                "source": "amass_genecore",
                "title": f"GeneCore summary for {symbol}",
                "text": summary,
                "url": "https://platform.amass.tech/",
            }
        )

    # -------------------------
    # Gene metadata
    # -------------------------
    metadata_parts = []

    name = record.get("name")
    gene_type = record.get("geneType")
    location = record.get("location")
    chromosome = record.get("chromosome")
    hgnc_id = record.get("hgncId")
    entrez_id = record.get("entrezGeneId")

    if name:
        metadata_parts.append(f"Gene name: {name}")

    if gene_type:
        metadata_parts.append(f"Gene type: {gene_type}")

    if location:
        metadata_parts.append(f"Cytogenetic location: {location}")

    if chromosome:
        metadata_parts.append(f"Chromosome: {chromosome}")

    if hgnc_id:
        metadata_parts.append(f"HGNC ID: {hgnc_id}")

    if entrez_id:
        metadata_parts.append(f"Entrez Gene ID: {entrez_id}")

    if metadata_parts:
        evidence.append(
            {
                "id": f"AMASS:metadata:{amass_id}",
                "source": "amass_genecore",
                "title": f"GeneCore metadata for {symbol}",
                "text": ". ".join(metadata_parts) + ".",
                "url": "https://platform.amass.tech/",
            }
        )

    # -------------------------
    # Protein information
    # -------------------------
    protein = record.get("protein") or {}
    function = protein.get("function") or {}

    protein_parts = []

    function_summary = function.get("functionSummary")
    associated_diseases = function.get("associatedDiseases")
    tissue_specificity = function.get("tissueSpecificity")
    subcellular_locations = function.get("subcellularLocations")

    if function_summary:
        protein_parts.append(f"Protein function: {function_summary}")

    if associated_diseases:
        protein_parts.append(f"Associated diseases: {associated_diseases}")

    if tissue_specificity:
        protein_parts.append(f"Tissue specificity: {tissue_specificity}")

    if subcellular_locations:
        protein_parts.append(f"Subcellular locations: " f"{subcellular_locations}")

    if protein_parts:
        evidence.append(
            {
                "id": f"AMASS:protein:{amass_id}",
                "source": "amass_genecore",
                "title": f"Protein information for {symbol}",
                "text": ". ".join(protein_parts) + ".",
                "url": "https://platform.amass.tech/",
            }
        )

    return evidence


def retrieve_amass_gene_evidence(
    gene_symbol: str,
    ensembl_id: str | None = None,
) -> list[dict]:
    """
    Retrieve exact GeneCore information for one gene and
    normalize it into GenCite evidence records.
    """

    record = get_amass_gene_record(
        gene_symbol=gene_symbol,
        ensembl_id=ensembl_id,
    )

    if not record:
        return []

    return _gene_record_to_evidence(
        record,
        fallback_symbol=gene_symbol,
    )


def _is_biomed_record_relevant(
    record: dict,
    gene_symbol: str,
    gene_name: str | None,
) -> bool:
    """
    Apply a conservative relevance check to BiomedCore results.

    This helps prevent ambiguous symbols such as LCT from matching
    unrelated biomedical meanings such as long-chain triglycerides.
    """

    title = record.get("title") or ""
    abstract = record.get("abstract") or ""

    text = f"{title} {abstract}".lower()

    if gene_name:
        gene_name_lower = gene_name.lower()

        if len(gene_name_lower) >= 4 and gene_name_lower in text:
            return True

    symbol_pattern = rf"\b{re.escape(gene_symbol.lower())}\b"

    symbol_present = bool(re.search(symbol_pattern, text))

    if not symbol_present:
        return False

    biological_context_terms = [
        "gene",
        "protein",
        "expression",
        "mutation",
        "variant",
        "genetic",
        "transcript",
        "mrna",
        "knockout",
        "knockdown",
        "allele",
        "genotype",
        "polymorphism",
    ]

    return any(term in text for term in biological_context_terms)


def retrieve_amass_biomed_evidence(
    gene_symbol: str,
    gene_name: str | None = None,
    max_results: int = 5,
) -> list[dict]:
    """
    Retrieve gene-relevant literature from AMASS BiomedCore.

    BiomedCore is treated as optional:
    if the request times out, return an empty list rather than
    failing the entire GenCite pipeline.
    """

    url = f"{AMASS_BASE_URL}/cores/" f"biomedcore/records"

    if gene_name:
        query = f"{gene_symbol} {gene_name} gene"
    else:
        query = f"{gene_symbol} gene"

    # Retrieve several candidates because we apply our own
    # relevance filtering afterward.
    candidate_limit = min(
        max(max_results * 3, 10),
        20,
    )

    params = {
        "query": query,
        "limit": candidate_limit,
        "isRetracted": "false",
    }

    try:
        response = requests.get(
            url,
            headers=_get_headers(),
            params=params,
            timeout=BIOMEDCORE_TIMEOUT,
        )

        response.raise_for_status()

    except requests.exceptions.Timeout:
        return []

    payload = _unwrap_data(response.json())

    if not isinstance(payload, list):
        return []

    evidence = []

    for record in payload:
        if not _is_biomed_record_relevant(
            record,
            gene_symbol=gene_symbol,
            gene_name=gene_name,
        ):
            continue

        amass_id = record.get("amassId")

        if not amass_id:
            continue

        pmid = record.get("pmid")
        doi = record.get("doi")
        title = record.get("title") or "Biomedical publication"
        abstract = record.get("abstract") or ""

        metadata_parts = []

        journal = record.get("journal")
        publication_date = record.get("publicationDate")
        citation_count = record.get("citationCount")

        if journal:
            metadata_parts.append(f"Journal: {journal}")

        if publication_date:
            metadata_parts.append(f"Publication date: " f"{publication_date}")

        if citation_count is not None:
            metadata_parts.append(f"Citation count: " f"{citation_count}")

        text_parts = []

        if abstract:
            text_parts.append(abstract)

        if metadata_parts:
            text_parts.append("Metadata: " + "; ".join(metadata_parts))

        if pmid:
            source_url = "https://pubmed.ncbi.nlm.nih.gov/" f"{pmid}/"

        elif doi:
            source_url = f"https://doi.org/{doi}"

        else:
            source_url = "https://platform.amass.tech/"

        evidence.append(
            {
                "id": f"AMASS:biomed:{amass_id}",
                "source": "amass_biomedcore",
                "title": title,
                "text": " ".join(text_parts),
                "url": source_url,
            }
        )

        if len(evidence) >= max_results:
            break

    return evidence


def retrieve_amass_evidence(
    gene_symbol: str,
    ensembl_id: str | None = None,
    max_biomed_results: int = 5,
) -> list[dict]:
    """
    Retrieve all available AMASS evidence for one gene.

    GeneCore is the primary AMASS source.
    BiomedCore is supplementary and failure-tolerant.
    """

    evidence = []

    gene_record = get_amass_gene_record(
        gene_symbol=gene_symbol,
        ensembl_id=ensembl_id,
    )

    if gene_record:
        gene_evidence = _gene_record_to_evidence(
            gene_record,
            fallback_symbol=gene_symbol,
        )

        evidence.extend(gene_evidence)

    gene_name = None

    if gene_record:
        gene_name = gene_record.get("name")

    try:
        biomed_evidence = retrieve_amass_biomed_evidence(
            gene_symbol=gene_symbol,
            gene_name=gene_name,
            max_results=max_biomed_results,
        )

        evidence.extend(biomed_evidence)

    except requests.RequestException:
        # AMASS BiomedCore is supplementary.
        # GeneCore evidence should still survive.
        pass

    return evidence

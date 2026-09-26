import re
import xml.etree.ElementTree as ET

import requests

ELINK_URL = "https://eutils.ncbi.nlm.nih.gov/" "entrez/eutils/elink.fcgi"

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/" "entrez/eutils/esearch.fcgi"

EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/" "entrez/eutils/efetch.fcgi"

NCBI_TIMEOUT = 10


def _unique_in_order(
    values: list[str],
) -> list[str]:
    """
    Remove duplicates while preserving the order supplied by NCBI.
    """
    seen = set()
    unique = []

    for value in values:
        if value in seen:
            continue

        seen.add(value)
        unique.append(value)

    return unique


def _extract_elink_pmids(
    xml_text: str,
    linkname: str,
) -> list[str]:
    """
    Extract PubMed IDs from an NCBI ELink response for
    one requested Gene -> PubMed link type.
    """

    root = ET.fromstring(xml_text)

    pmids = []

    for linkset_db in root.findall(".//LinkSetDb"):
        returned_linkname = linkset_db.findtext("LinkName")

        if returned_linkname != linkname:
            continue

        for id_element in linkset_db.findall("./Link/Id"):
            if id_element.text:
                pmids.append(id_element.text)

    return _unique_in_order(pmids)


def get_gene_linked_pmids(
    entrez_id: str,
    linkname: str,
) -> list[str]:
    """
    Retrieve PubMed IDs explicitly linked by NCBI
    to one Entrez Gene record.

    Examples of link types:
    - gene_pubmed_rif: GeneRIF-associated publications
    - gene_pubmed: broader Gene-associated publications
    """

    params = {
        "dbfrom": "gene",
        "db": "pubmed",
        "id": entrez_id,
        "linkname": linkname,
        "cmd": "neighbor",
        "retmode": "xml",
    }

    response = requests.get(
        ELINK_URL,
        params=params,
        timeout=NCBI_TIMEOUT,
    )
    response.raise_for_status()

    return _extract_elink_pmids(
        response.text,
        linkname=linkname,
    )


def get_prioritized_gene_pmids(
    entrez_id: str,
    max_results: int = 5,
) -> list[str]:
    """
    Retrieve PubMed IDs explicitly associated with a gene.

    GeneRIF publications are preferred because they represent
    gene/function-specific literature relationships.

    If fewer than max_results GeneRIF publications exist,
    fill the remaining slots from the broader NCBI Gene -> PubMed
    links.

    If NCBI returns only a small number of explicitly linked papers,
    keep the evidence sparse rather than filling the result with
    potentially ambiguous text-search hits.
    """

    selected = []
    seen = set()

    linknames = [
        "gene_pubmed_rif",
        "gene_pubmed",
    ]

    for linkname in linknames:
        try:
            linked_pmids = get_gene_linked_pmids(
                entrez_id=entrez_id,
                linkname=linkname,
            )

        except (
            requests.exceptions.RequestException,
            ET.ParseError,
        ):
            # Try the next explicit link source.
            # Text search remains available as a final fallback
            # only if no linked papers can be obtained at all.
            continue

        for pmid in linked_pmids:
            if pmid in seen:
                continue

            seen.add(pmid)
            selected.append(pmid)

            if len(selected) >= max_results:
                return selected

    return selected


def fetch_pubmed_records(
    pmids: list[str],
) -> list[dict]:
    """
    Fetch PubMed titles and abstracts for a list of PMIDs.
    """

    if not pmids:
        return []

    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
    }

    response = requests.get(
        EFETCH_URL,
        params=params,
        timeout=NCBI_TIMEOUT,
    )
    response.raise_for_status()

    root = ET.fromstring(response.text)

    records = []

    # Journal articles and book chapters such as GeneReviews
    # both carry PubMed IDs and are useful gene evidence.
    articles = root.findall(".//PubmedArticle") + root.findall(".//PubmedBookArticle")

    for article in articles:
        pmid = article.findtext(".//PMID")

        if not pmid:
            continue

        title_element = article.find(".//ArticleTitle")

        # Some PubMed book records may expose a book title
        # instead of an article/chapter title.
        if title_element is None:
            title_element = article.find(".//BookTitle")

        title = "".join(title_element.itertext()) if title_element is not None else ""

        abstract_parts = []

        for abstract_text in article.findall(".//AbstractText"):
            abstract_parts.append("".join(abstract_text.itertext()))

        abstract = " ".join(abstract_parts)

        records.append(
            {
                "id": f"PMID:{pmid}",
                "source": "pubmed",
                "title": title,
                "text": abstract,
                "url": ("https://pubmed.ncbi.nlm.nih.gov/" f"{pmid}/"),
            }
        )

    return records


def _escape_pubmed_phrase(
    text: str,
) -> str:
    """
    Make text safe to use inside a quoted PubMed search phrase.
    """

    return text.replace('"', "").strip()


def search_pubmed_by_text(
    gene_symbol: str,
    gene_name: str | None = None,
    max_results: int = 15,
) -> list[str]:
    """
    Fallback PubMed search.

    This route is only used if the resolved gene has no usable
    NCBI Gene -> PubMed links.
    """

    symbol = _escape_pubmed_phrase(gene_symbol)

    if gene_name:
        name = _escape_pubmed_phrase(gene_name)

        term = f'("{symbol}"[Title/Abstract] ' f'OR "{name}"[Title/Abstract])'

    else:
        term = f'"{symbol}"[Title/Abstract]'

    params = {
        "db": "pubmed",
        "term": term,
        "retmode": "json",
        "retmax": max_results,
        "sort": "relevance",
    }

    response = requests.get(
        ESEARCH_URL,
        params=params,
        timeout=NCBI_TIMEOUT,
    )
    response.raise_for_status()

    data = response.json()

    return data.get(
        "esearchresult",
        {},
    ).get("idlist", [])


def _symbol_has_direct_gene_context(
    text: str,
    gene_symbol: str,
) -> bool:
    """
    Conservative fallback check for ambiguous gene symbols.

    Require the symbol to occur directly next to gene-related
    terminology rather than accepting a generic occurrence of words
    such as 'gene' somewhere else in the abstract.
    """

    symbol = re.escape(gene_symbol.lower())

    context_terms = (
        "gene",
        "genes",
        "protein",
        "proteins",
        "expression",
        "expressed",
        "mutation",
        "mutations",
        "variant",
        "variants",
        "genetic",
        "transcript",
        "transcripts",
        "mrna",
        "allele",
        "alleles",
        "genotype",
        "polymorphism",
        "polymorphisms",
        "promoter",
        "knockout",
        "knockdown",
        "deficiency",
        "receptor",
    )

    context_pattern = "|".join(re.escape(term) for term in context_terms)

    after_symbol = re.compile(
        rf"\b{symbol}\b" rf"[\s\-/:,()]{{1,12}}" rf"\b(?:{context_pattern})\b"
    )

    before_symbol = re.compile(
        rf"\b(?:{context_pattern})\b" rf"[\s\-/:,()]{{1,12}}" rf"\b{symbol}\b"
    )

    return bool(after_symbol.search(text) or before_symbol.search(text))


def _is_text_fallback_relevant(
    record: dict,
    gene_symbol: str,
    gene_name: str | None,
) -> bool:
    """
    Conservative relevance check for text-search fallback results.

    The official full gene name is considered strong evidence of
    relevance. Otherwise, the symbol must appear immediately in
    gene-related biological context.
    """

    title = record.get("title") or ""
    abstract = record.get("text") or ""

    text = (f"{title} {abstract}").lower()

    if gene_name:
        normalized_name = gene_name.lower().strip()

        if len(normalized_name) >= 4 and normalized_name in text:
            return True

    return _symbol_has_direct_gene_context(
        text,
        gene_symbol=gene_symbol,
    )


def retrieve_pubmed_text_fallback(
    gene_symbol: str,
    gene_name: str | None = None,
    max_results: int = 5,
) -> list[dict]:
    """
    Retrieve PubMed evidence using text search as a fallback.

    More candidates are requested than ultimately returned because
    ambiguous acronym matches are filtered locally.
    """

    candidate_count = min(
        max(max_results * 3, 10),
        20,
    )

    pmids = search_pubmed_by_text(
        gene_symbol=gene_symbol,
        gene_name=gene_name,
        max_results=candidate_count,
    )

    records = fetch_pubmed_records(pmids)

    relevant_records = []

    for record in records:
        if not _is_text_fallback_relevant(
            record,
            gene_symbol=gene_symbol,
            gene_name=gene_name,
        ):
            continue

        relevant_records.append(record)

        if len(relevant_records) >= max_results:
            break

    return relevant_records


def retrieve_pubmed_evidence(
    gene_symbol: str,
    gene_name: str | None = None,
    entrez_id: str | None = None,
    max_results: int = 5,
) -> list[dict]:
    """
    Retrieve gene-specific PubMed evidence.

    Preferred route:
        Entrez Gene ID -> NCBI Gene/PubMed links

    Fallback route:
        symbol/name PubMed text search + conservative relevance filter

    If NCBI has even a small amount of explicitly gene-linked
    literature, keep that sparse set instead of padding it with
    less certain text-search results.
    """

    if entrez_id:
        linked_pmids = get_prioritized_gene_pmids(
            entrez_id=entrez_id,
            max_results=max_results,
        )

        if linked_pmids:
            return fetch_pubmed_records(linked_pmids)

    return retrieve_pubmed_text_fallback(
        gene_symbol=gene_symbol,
        gene_name=gene_name,
        max_results=max_results,
    )

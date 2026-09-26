import os
from collections import Counter

from dotenv import load_dotenv

load_dotenv()

import streamlit as st

from gencite.collect_evidence import (
    DEFAULT_EVIDENCE_SOURCES,
    collect_evidence,
)
from gencite.create_report import build_report
from gencite.ids import resolve_gene_id
from gencite.inputs import parse_gene_list
from gencite.schema import GeneRecord
from gencite.synth_LLM import synthesize
from gencite.verify import JUDGE_FAILED, verify


# ---------------------------------------------------------
# Streamlit page configuration
# ---------------------------------------------------------

st.set_page_config(
    page_title="gencite",
    page_icon="🧬",
    layout="wide",
)


# ---------------------------------------------------------
# Display configuration
# ---------------------------------------------------------

SOURCE_LABELS = {
    "pubmed": "NCBI PubMed",
    "open_targets": "Open Targets",
    "human_protein_atlas": "Human Protein Atlas",
    "amass": "AMASS",
}

SOURCE_DESCRIPTIONS = {
    "pubmed": (
        "Gene-linked scientific literature from NCBI PubMed."
    ),
    "open_targets": (
        "Structured target information and disease associations."
    ),
    "human_protein_atlas": (
        "Tissue, cell-type, and biological annotation."
    ),
    "amass": (
        "AMASS GeneCore annotations and BiomedCore literature."
    ),
}

SOURCE_ORDER = [
    "pubmed",
    "open_targets",
    "human_protein_atlas",
    "amass",
]

VERDICT_LABELS = {
    "supported": "Supported",
    "partial": "Partially supported",
    "unsupported": "Unsupported",
    "invalid_id": "Invalid citation",
    "unchecked": "Unchecked",
}

VERDICT_ICONS = {
    "supported": "✅",
    "partial": "🟡",
    "unsupported": "❌",
    "invalid_id": "⚠️",
    "unchecked": "❔",
}


# ---------------------------------------------------------
# Styling
# ---------------------------------------------------------

st.markdown(
    """
    <style>
        .block-container {
            max-width: 1180px;
            padding-top: 2rem;
            padding-bottom: 4rem;
        }

        .gencite-hero {
            padding: 2.2rem 2.4rem;
            margin-bottom: 1.6rem;
            border-radius: 20px;
            background:
                linear-gradient(
                    135deg,
                    #16213e 0%,
                    #243b55 55%,
                    #355c7d 100%
                );
            color: white;
        }

        .gencite-hero h1 {
            margin: 0;
            padding: 0;
            color: white;
            font-size: 2.7rem;
        }

        .gencite-hero p {
            margin-top: 0.55rem;
            margin-bottom: 0;
            font-size: 1.05rem;
            color: #e8eef6;
        }

        .source-caption {
            color: #6b7280;
            font-size: 0.88rem;
        }

        div[data-testid="stMetric"] {
            border: 1px solid rgba(128, 128, 128, 0.22);
            padding: 1rem;
            border-radius: 14px;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------
# Helper functions
# ---------------------------------------------------------

def escape_markdown(text: str) -> str:
    """
    Show text literally in st.markdown.

    Abstracts and claims can contain characters that Markdown
    would interpret, e.g. '*' (italics) or '$' (LaTeX).
    """

    for char in "\\`*_[]<>#|$~":
        text = text.replace(
            char,
            "\\" + char,
        )

    return text


def evidence_source_group(source: str) -> str:
    """
    Map detailed internal source names to the four user-facing
    evidence-source groups.
    """

    if source == "pubmed":
        return "pubmed"

    if source == "open_targets":
        return "open_targets"

    if source == "human_protein_atlas":
        return "human_protein_atlas"

    if source.startswith("amass"):
        return "amass"

    return source


def evidence_source_label(source: str) -> str:
    """
    Return a readable source label for one evidence item.
    """

    group = evidence_source_group(source)

    return SOURCE_LABELS.get(
        group,
        source.replace("_", " ").title(),
    )


def count_record_sources(
    record: GeneRecord,
) -> Counter:
    """
    Count retained evidence records by user-facing source.
    """

    counts = Counter()

    for item in record.evidence:
        counts[
            evidence_source_group(item.source)
        ] += 1

    return counts


def evidence_links_for_claim(
    claim,
    record: GeneRecord,
) -> str:
    """
    Create clickable evidence links for one verified claim.
    """

    evidence_by_id = {
        item.id: item
        for item in record.evidence
    }

    links = []

    for evidence_id in claim.evidence_ids:
        evidence = evidence_by_id.get(
            evidence_id
        )

        if evidence and evidence.url:
            links.append(
                f"[`{evidence_id}`]"
                f"({evidence.url})"
            )
        else:
            links.append(
                f"`{evidence_id}`"
            )

    return ", ".join(links)


def run_analysis(
    genes: list[str],
    enabled_sources: set[str],
) -> dict:
    """
    Run retrieval for all genes.

    If an LLM API key is configured, also run the existing
    synthesizer and verifier pipeline.

    Retrieval results survive even if synthesis fails.
    """

    records = []
    verified_by_gene = {}

    source_errors = {}
    pipeline_errors = {}
    gene_names = {}

    llm_configured = bool(
        os.getenv("LLM_API_KEY")
    )

    progress = st.progress(
        0.0,
        text="Starting analysis...",
    )

    total = len(genes)

    seen_resolved_symbols = set()

    for index, symbol in enumerate(
        genes,
        start=1,
    ):
        progress.progress(
            (index - 1) / total,
            text=(
                f"Retrieving evidence for "
                f"{symbol} "
                f"({index}/{total})..."
            ),
        )

        # Start with the uploaded symbol.
        # Once resolution succeeds, this is replaced by the
        # canonical human gene symbol returned by MyGene.
        resolved_symbol = symbol

        try:
            gene_info = resolve_gene_id(
                symbol
            )

            resolved_symbol = (
                    gene_info.get("symbol")
                    or symbol
            )

            if resolved_symbol in seen_resolved_symbols:
                progress.progress(
                    index / total,
                    text=(
                        f"Skipped duplicate "
                        f"{resolved_symbol} "
                        f"({index}/{total})"
                    ),
                )
                continue

            seen_resolved_symbols.add(
                resolved_symbol
            )

            gene_names[
                resolved_symbol
            ] = gene_info.get(
                "name"
            )

            raw = collect_evidence(
                gene_info,
                enabled_sources=enabled_sources,
            )

            record = GeneRecord.model_validate(
                raw
            )

            records.append(record)

            errors = raw.get(
                "errors",
                [],
            )

            if errors:
                source_errors[
                    resolved_symbol
                ] = errors

        except Exception as exc:
            pipeline_errors[
                resolved_symbol
            ] = [
                (
                    "Retrieval failed: "
                    f"{type(exc).__name__}: "
                    f"{exc}"
                )
            ]

            progress.progress(
                index / total,
                text=(
                    f"Finished {index}/{total}"
                ),
            )
            continue

        # ---------------------------------------------
        # LLM synthesis + verification
        # ---------------------------------------------

        if llm_configured:
            progress.progress(
                (index - 0.45) / total,
                text=(
                    f"Synthesizing and verifying "
                    f"{resolved_symbol}..."
                ),
            )

            try:
                synth = synthesize(
                    record
                )

                verified = verify(
                    synth,
                    record,
                    use_llm=True,
                )

                verified_by_gene[
                    resolved_symbol
                ] = verified

            except Exception as exc:
                pipeline_errors.setdefault(
                    resolved_symbol,
                    [],
                ).append(
                    (
                        "Synthesis or verification "
                        "failed: "
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    )
                )

        progress.progress(
            index / total,
            text=(
                f"Finished {index}/{total}"
            ),
        )

    progress.empty()

    return {
        "genes": list(genes),
        "records": records,
        "verified_by_gene": (
            verified_by_gene
        ),
        "source_errors": source_errors,
        "pipeline_errors": (
            pipeline_errors
        ),
        "gene_names": gene_names,
        "enabled_sources": set(
            enabled_sources
        ),
        "llm_configured": (
            llm_configured
        ),
    }


def render_claims(
    verified,
    record: GeneRecord,
) -> None:
    """
    Render verified claims for one gene.
    """

    if verified.note:
        st.info(
            verified.note
        )

    if not verified.claims:
        st.info(
            "No evidence-supported claims "
            "were generated for this gene."
        )
        return

    st.markdown(
        "#### Evidence-grounded claims"
    )

    for claim_number, claim in enumerate(
        verified.claims,
        start=1,
    ):
        with st.container(
            border=True
        ):
            icon = VERDICT_ICONS.get(
                claim.verdict,
                "•",
            )

            label = VERDICT_LABELS.get(
                claim.verdict,
                claim.verdict,
            )

            st.markdown(
                f"**{icon} {label}**"
            )

            st.markdown(
                f"**{claim_number}. "
                f"{escape_markdown(claim.text)}**"
            )

            source_links = (
                evidence_links_for_claim(
                    claim,
                    record,
                )
            )

            if source_links:
                st.markdown(
                    "**Sources:** "
                    + source_links
                )

            if claim.reason:
                st.caption(
                    "Verifier: "
                    + escape_markdown(claim.reason)
                )

            # A failed judge call is not cached, so a new run
            # retries only these claims.
            if claim.reason.startswith(
                JUDGE_FAILED
            ):
                st.caption(
                    "The judge call failed (e.g. rate limit). "
                    "Click Analyse genes again to retry; "
                    "claims that were already judged come "
                    "from the cache."
                )


def render_evidence(
    record: GeneRecord,
) -> None:
    """
    Render all retained evidence for one gene.
    """

    with st.expander(
        (
            "Retrieved evidence "
            f"({len(record.evidence)})"
        )
    ):
        if not record.evidence:
            st.write(
                "No evidence was retrieved "
                "from the selected sources."
            )
            return

        for index, item in enumerate(
            record.evidence
        ):
            source_label = (
                evidence_source_label(
                    item.source
                )
            )

            st.markdown(
                f"**{source_label}** "
                f"· `{item.id}`"
            )

            if item.title:
                st.markdown(
                    f"**{escape_markdown(item.title)}**"
                )

            if item.text:
                st.markdown(
                    escape_markdown(item.text)
                )

            if item.url:
                st.markdown(
                    f"[Open source ↗]"
                    f"({item.url})"
                )

            if (
                index
                < len(record.evidence) - 1
            ):
                st.divider()


def render_gene_result(
    record: GeneRecord,
    analysis: dict,
) -> None:
    """
    Render one gene result card.
    """

    symbol = record.gene.symbol

    verified = (
        analysis[
            "verified_by_gene"
        ].get(symbol)
    )

    gene_name = (
        analysis[
            "gene_names"
        ].get(symbol)
    )

    with st.container(
        border=True
    ):
        title_col, status_col = (
            st.columns(
                [3, 1]
            )
        )

        with title_col:
            st.subheader(symbol)

            if gene_name:
                st.caption(
                    gene_name
                )

        with status_col:
            if verified:
                st.metric(
                    "Evidence level",
                    verified.evidence_level.title(),
                )
            else:
                st.metric(
                    "Evidence records",
                    len(record.evidence),
                )

        if not record.gene.found:
            st.warning(
                "This symbol could not be "
                "resolved as a human gene."
            )

        else:
            metadata_parts = []

            if record.gene.gene_type:
                metadata_parts.append(
                    "**Type:** "
                    + record.gene.gene_type
                )

            if record.gene.ensembl_id:
                ensembl = (
                    record.gene.ensembl_id
                )

                metadata_parts.append(
                    "**Ensembl:** "
                    f"[{ensembl}]"
                    "("
                    "https://www.ensembl.org/"
                    "Homo_sapiens/Gene/"
                    f"Summary?g={ensembl}"
                    ")"
                )

            if record.gene.entrez_id:
                entrez = (
                    record.gene.entrez_id
                )

                metadata_parts.append(
                    "**Entrez:** "
                    f"[{entrez}]"
                    "("
                    "https://www.ncbi.nlm.nih.gov/"
                    f"gene/{entrez}"
                    ")"
                )

            if metadata_parts:
                st.markdown(
                    " · ".join(
                        metadata_parts
                    )
                )

        source_counts = (
            count_record_sources(
                record
            )
        )

        count_text = []

        for source in SOURCE_ORDER:
            if (
                source
                not in analysis[
                    "enabled_sources"
                ]
            ):
                continue

            count_text.append(
                (
                    f"{SOURCE_LABELS[source]}: "
                    f"{source_counts[source]}"
                )
            )

        if count_text:
            st.caption(
                "Evidence by source · "
                + " · ".join(
                    count_text
                )
            )

        if verified:
            render_claims(
                verified,
                record,
            )

        elif not analysis[
            "llm_configured"
        ]:
            st.info(
                "Evidence retrieval completed. "
                "LLM synthesis and verification "
                "are not configured on this "
                "machine, so the retrieved "
                "evidence is shown below."
            )

        elif symbol in analysis[
            "pipeline_errors"
        ]:
            st.warning(
                "Evidence was retrieved, but "
                "claim synthesis or verification "
                "did not complete."
            )

        gene_source_errors = (
            analysis[
                "source_errors"
            ].get(
                symbol,
                [],
            )
        )

        gene_pipeline_errors = (
            analysis[
                "pipeline_errors"
            ].get(
                symbol,
                [],
            )
        )

        if (
            gene_source_errors
            or gene_pipeline_errors
        ):
            with st.expander(
                "Warnings"
            ):
                for error in (
                    gene_source_errors
                ):
                    st.warning(
                        (
                            f"{error.get('source', 'source')}: "
                            f"{error.get('message', '')}"
                        )
                    )

                for error in (
                    gene_pipeline_errors
                ):
                    st.warning(
                        error
                    )

        render_evidence(
            record
        )


# ---------------------------------------------------------
# Header
# ---------------------------------------------------------

st.markdown(
    """
    <div class="gencite-hero">
        <h1>gencite</h1>
        <p>
            Evidence-grounded interpretation of human gene lists,
            with traceable sources and claim verification.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

st.caption(
    "gencite currently supports Homo sapiens genes."
)


# ---------------------------------------------------------
# Input and source selection
# ---------------------------------------------------------

input_col, source_col = st.columns(
    [1.25, 1]
)

with input_col:
    st.subheader(
        "1. Upload a gene list"
    )

    uploaded_file = st.file_uploader(
        (
            "Drag and drop a .txt file "
            "containing one human gene "
            "symbol per line"
        ),
        type=["txt"],
        help=(
            "Headers such as 'Gene' or "
            "'Symbol', blank lines, "
            "comments, and duplicates "
            "are handled automatically."
        ),
    )

    genes = []

    if uploaded_file is not None:
        try:
            uploaded_text = (
                uploaded_file
                .getvalue()
                .decode(
                    "utf-8-sig"
                )
            )

            genes = parse_gene_list(
                uploaded_text
            )

            if genes:
                st.success(
                    (
                        f"{len(genes)} unique "
                        "gene symbol"
                        f"{'s' if len(genes) != 1 else ''} "
                        "detected."
                    )
                )

                with st.expander(
                    "Preview gene list"
                ):
                    st.write(
                        ", ".join(genes)
                    )

            else:
                st.warning(
                    "No gene symbols were "
                    "found in this file."
                )

        except UnicodeDecodeError:
            st.error(
                "The uploaded file could not "
                "be read as UTF-8 text."
            )

with source_col:
    st.subheader(
        "2. Choose evidence sources"
    )

    source_left, source_right = (
        st.columns(2)
    )

    with source_left:
        use_pubmed = st.checkbox(
            "NCBI PubMed",
            value=True,
            help=(
                SOURCE_DESCRIPTIONS[
                    "pubmed"
                ]
            ),
        )

        use_hpa = st.checkbox(
            "Human Protein Atlas",
            value=True,
            help=(
                SOURCE_DESCRIPTIONS[
                    "human_protein_atlas"
                ]
            ),
        )

    with source_right:
        use_open_targets = (
            st.checkbox(
                "Open Targets",
                value=True,
                help=(
                    SOURCE_DESCRIPTIONS[
                        "open_targets"
                    ]
                ),
            )
        )

        use_amass = st.checkbox(
            "AMASS",
            value=True,
            help=(
                SOURCE_DESCRIPTIONS[
                    "amass"
                ]
            ),
        )

    st.caption(
        (
            "MyGene.info is always used "
            "for human gene identifier "
            "resolution and is not an "
            "optional evidence source."
        )
    )


selected_sources = set()

if use_pubmed:
    selected_sources.add(
        "pubmed"
    )

if use_open_targets:
    selected_sources.add(
        "open_targets"
    )

if use_hpa:
    selected_sources.add(
        "human_protein_atlas"
    )

if use_amass:
    selected_sources.add(
        "amass"
    )


# ---------------------------------------------------------
# Configuration messages
# ---------------------------------------------------------

if (
    use_amass
    and not os.getenv(
        "AMASS_API_KEY"
    )
):
    st.warning(
        "AMASS is selected, but "
        "`AMASS_API_KEY` is not configured. "
        "The other selected sources will "
        "still run."
    )

llm_configured = bool(
    os.getenv("LLM_API_KEY")
)

if not llm_configured:
    st.info(
        "No `LLM_API_KEY` is configured on "
        "this machine. You can still test "
        "gene resolution, source selection, "
        "evidence retrieval, and the UI. "
        "Claim synthesis and verification "
        "will activate automatically when "
        "the final LLM configuration is "
        "available."
    )


# ---------------------------------------------------------
# Analyse button
# ---------------------------------------------------------

st.subheader(
    "3. Analyse"
)

if not selected_sources:
    st.warning(
        "Select at least one evidence source."
    )

analyse_clicked = st.button(
    "Analyse genes",
    type="primary",
    use_container_width=True,
    disabled=(
        not genes
        or not selected_sources
    ),
)

if analyse_clicked:
    analysis = run_analysis(
        genes=genes,
        enabled_sources=(
            selected_sources
        ),
    )

    st.session_state[
        "gencite_analysis"
    ] = analysis


# ---------------------------------------------------------
# Results
# ---------------------------------------------------------

analysis = st.session_state.get(
    "gencite_analysis"
)

# Results belong to the gene list and sources they were run with.
# If the file or the source selection changed since, drop them
# instead of showing them next to the new inputs.
if analysis and (
    analysis["genes"] != genes
    or analysis["enabled_sources"] != selected_sources
):
    del st.session_state[
        "gencite_analysis"
    ]

    analysis = None

    st.info(
        "The gene list or the source selection changed. "
        "Click Analyse genes to run the analysis again."
    )

if analysis:
    st.divider()

    st.markdown(
        "## Results"
    )

    records = analysis[
        "records"
    ]

    if not records:
        st.error(
            "No genes were successfully "
            "processed."
        )

        # If every retrieval failed, show the captured exceptions
        # instead of hiding them behind the record-dependent UI.
        if analysis[
            "pipeline_errors"
        ]:
            with st.expander(
                "Error details"
            ):
                for symbol, errors in (
                    analysis[
                        "pipeline_errors"
                    ].items()
                ):
                    for error in errors:
                        st.error(
                            f"{symbol}: {error}"
                        )

    else:
        total_evidence = sum(
            len(record.evidence)
            for record in records
        )

        verified_results = [
            analysis[
                "verified_by_gene"
            ][record.gene.symbol]
            for record in records
            if record.gene.symbol
            in analysis[
                "verified_by_gene"
            ]
        ]

        total_claims = sum(
            len(result.claims)
            for result in verified_results
        )

        supported_claims = sum(
            (
                claim.verdict
                == "supported"
            )
            for result
            in verified_results
            for claim
            in result.claims
        )

        metric_1, metric_2, metric_3, metric_4 = (
            st.columns(4)
        )

        metric_1.metric(
            "Genes processed",
            len(records),
        )

        metric_2.metric(
            "Evidence records",
            total_evidence,
        )

        metric_3.metric(
            "Claims",
            (
                total_claims
                if analysis[
                    "llm_configured"
                ]
                else "Not run"
            ),
        )

        metric_4.metric(
            "Supported claims",
            (
                supported_claims
                if analysis[
                    "llm_configured"
                ]
                else "Not run"
            ),
        )

        source_summary = Counter()

        for record in records:
            source_summary.update(
                count_record_sources(
                    record
                )
            )

        source_summary_text = []

        for source in SOURCE_ORDER:
            if (
                source
                not in analysis[
                    "enabled_sources"
                ]
            ):
                continue

            source_summary_text.append(
                (
                    f"{SOURCE_LABELS[source]}: "
                    f"{source_summary[source]}"
                )
            )

        if source_summary_text:
            st.caption(
                "Unique retained evidence · "
                + " · ".join(
                    source_summary_text
                )
            )

        # ---------------------------------------------
        # Download final Markdown report
        # ---------------------------------------------

        if verified_results:
            records_by_symbol = {
                record.gene.symbol: record
                for record in records
            }

            markdown_report = (
                build_report(
                    verified_results,
                    records_by_symbol,
                )
            )

            st.download_button(
                label=(
                    "Download Markdown report"
                ),
                data=markdown_report,
                file_name=(
                    "gencite_report.md"
                ),
                mime="text/markdown",
            )

        # ---------------------------------------------
        # Fatal retrieval failures
        # ---------------------------------------------

        if analysis[
            "pipeline_errors"
        ]:
            failed_before_record = [
                symbol
                for symbol
                in analysis[
                    "pipeline_errors"
                ]
                if symbol
                not in {
                    record.gene.symbol
                    for record
                    in records
                }
            ]

            if failed_before_record:
                with st.expander(
                    (
                        "Genes that could not "
                        "be processed"
                    )
                ):
                    for symbol in (
                        failed_before_record
                    ):
                        st.error(
                            symbol
                            + ": "
                            + " | ".join(
                                analysis[
                                    "pipeline_errors"
                                ][symbol]
                            )
                        )

        # ---------------------------------------------
        # Per-gene result cards
        # ---------------------------------------------

        for record in records:
            render_gene_result(
                record,
                analysis,
            )
# gencite


## Motivation

Almost every omics analysis ends with a gene list that someone has to interpret: selection scans, RNA-seq, GWAS loci, CRISPR screens. Today that usually means looking up each gene by hand in PubMed and gene databases, which is slow. Asking a plain LLM instead is fast, but its answers cannot be traced back to a source and it invents citations.

## Goal

gencite does the lookup and a first written summary for every gene, and makes each statement checkable:

- **Every claim cites evidence.** The LLM may only use the retrieved evidence, and every claim names the PubMed or Open Targets record it is based on.
- **Every citation is checked in code.** A claim that cites an ID not retrieved for that gene is flagged (`invalid_id`).
- **Every claim is checked against its source.** A second LLM call (the judge) reads the claim and only the evidence it cites, and rates it `supported`, `partial` or `unsupported` with a one-line reason.
- **Honest about missing evidence.** Genes without usable evidence (unresolved symbols, most pseudogenes) get no claims and a note that says why.

The result is one Markdown report that a scientist can read and verify, with a link to every source.

## How it works

```
gene list ─► 1 parse ─► 2 resolve IDs ─► 3 PubMed ─► 4 Open Targets ─► 5 evidence per gene   records/
         ─► 6 synthesizer (LLM): short claims, each citing evidence IDs                        synth/
         ─► 7 ID check (code) ─► 8 judge (LLM): supported / partial / unsupported              verified/
         ─► 9 report                                                                           report.md
```

| Step | What happens | Source |
|---|---|---|
| 1 | Read the list; header line, comments, blanks and duplicates are removed | `inputs.py` |
| 2 | Symbol → Ensembl / Entrez ID and gene type | MyGene.info |
| 3 | Top 5 abstracts that mention the gene | PubMed (NCBI E-utilities) |
| 4 | Gene biotype and top disease associations | Open Targets |
| 5 | Evidence items with IDs (`PMID:…`, `OT:…`) per gene | `collect_evidence.py` |
| 6 | Up to 5 claims, each citing evidence IDs, plus an evidence level `sufficient` / `limited` / `none` | LLM |
| 7 | Every cited ID must be in this gene's evidence | code |
| 8 | Each claim is judged against the text it cites | LLM (can be a different model) |
| 9 | Summary table + one section per gene with claims, status and source links | `create_report.py` |

## Requirements

- Python 3.10 or newer
- Internet access to MyGene.info, NCBI E-utilities and the Open Targets API (all free, no key needed)
- An API key for an OpenAI-compatible LLM endpoint (DeepSeek, Groq, Gemini, OpenAI, a local Ollama server, …)

Python packages (`requirement.txt`):

| Package | Used for |
|---|---|
| `requests` | MyGene.info, PubMed and Open Targets calls |
| `openai` | LLM calls (any OpenAI-compatible endpoint) |
| `pydantic` | data schemas and validation of the LLM output |
| `python-dotenv` | reading the configuration from `.env` |

## Installation

```bash
git clone https://github.com/nomis-c/gencite.git
cd gencite
python3 -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirement.txt
```

## Configuration

There is no config file. Settings live in two places:

- **`.env`** for the LLM endpoint, model and key (per machine, never committed)
- **command-line flags** for everything that changes per run (see [Usage](#usage))

```bash
cp .env.example .env               # then fill in LLM_API_KEY
```

| Variable | Required | Meaning |
|---|---|---|
| `LLM_BASE_URL` | no (default `https://api.deepseek.com`) | endpoint for the synthesizer |
| `LLM_MODEL` | no (default `deepseek-chat`) | model for the synthesizer |
| `LLM_API_KEY` | **yes** | API key |
| `JUDGE_BASE_URL`, `JUDGE_MODEL`, `JUDGE_API_KEY` | no | a different model as judge; each empty value falls back to `LLM_*` |
| `GENCITE_NO_CACHE` | no | `1` turns the cache off (same as `--no-cache`) |

## Usage

Run the whole pipeline on the example list (15 genes, about 3–4 minutes on the first run):

```bash
python cli.py test_data/gene_list.txt
```

Then open `output/run/report.md` (e.g. in the PyCharm or VS Code Markdown preview).

Your own list is a text file with one gene symbol per line. A header line such as `Gene` or `Symbol` is detected and skipped.

### Commands

| Command | What it does |
|---|---|
| `python cli.py <genes.txt>` | whole pipeline, steps 1–9 |
| `python cli.py <genes.txt> --out output/my_run` | write to another folder (default `output/run`) |
| `python cli.py <genes.txt> --no-judge` | skip the judge (step 8), claims get `?`, fewer LLM calls |
| `python cli.py <genes.txt> --no-cache` | ask the LLM again instead of using cached answers |
| `python cli.py <records folder>` | steps 6–9 on saved evidence, e.g. `output/run/records` or `test_data` |
| `python cli.py --help` | all options |
| `python cache.py` / `python cache.py --clear` | show / delete the LLM cache in `data/cache/` |

Single steps, e.g. to look at the prompts or rerun one stage:

| Step | Command |
|---|---|
| 6 synthesizer | `python synth_LLM.py <records> [--out DIR] [--dry-run]` |
| 7–8 verifier | `python verify.py <synth> <records> [--out DIR] [--no-llm] [--dry-run]` |
| 9 report | `python create_report.py <verified> <records> [--out FILE]` |

`--dry-run` prints the LLM prompts without calling the LLM, `--no-llm` runs only the ID check.

### Output

`output/run/`:

| Path | Content |
|---|---|
| `records/` | retrieved evidence per gene (JSON) |
| `synth/` | claims with the cited evidence IDs (JSON) |
| `verified/` | claims with status and the judge's reason (JSON) |
| `report.md` | summary table and one section per gene: gene type, Ensembl link, evidence level, claims with status, source links, and all retrieved evidence marked "cited" or "not cited" |

Claim status in the report:

| Mark | Status | Meaning |
|---|---|---|
| `+` | supported | the cited evidence states the claim |
| `~` | partial | only part is backed, or the claim overstates it (e.g. association → causation, mouse → human) |
| `-` | unsupported | the cited evidence does not back the claim |
| `X` | invalid_id | the claim cites an ID that was not retrieved for this gene |
| `?` | unchecked | the judge was skipped (`--no-judge`) or its call failed |

Exit code 1 means some genes or claims failed, usually because of an LLM rate limit. Run the same command again: finished LLM calls come from the cache, only the failed ones are repeated.

## Testing

`test_data/` holds hand-written evidence for 6 genes with made-up PMIDs, including traps (a readthrough whose evidence is about its partner gene, a pseudogene, an unresolved symbol), and `test_data/synth_bad/` holds deliberately wrong claims for the verifier. This runs steps 6–9 without any retrieval:

```bash
python cli.py test_data --out output/run_testdata
```

`test.md` lists manual checks for every part with the expected output, including a full end-to-end run (section "End-to-end run").

## Project structure

```
cli.py                 entry point: whole pipeline
inputs.py              1  gene list parsing
ids.py                 2  MyGene.info ID resolution
pubmed_retrieval.py    3  PubMed search + abstracts
opentargets.py         4  Open Targets associations
collect_evidence.py    5  evidence per gene
synth_LLM.py           6  synthesizer
verify.py              7+8 ID check and LLM judge
create_report.py       9  Markdown report
schema.py              data shapes shared by all steps (pydantic)
llm_client.py          LLM calls: config from .env, retries, JSON validation, cache
cache.py               disk cache in data/cache/
test_data/             dummy evidence, example gene list, wrong claims for the verifier
test.md                manual test checklist
```

## Known limitations

- Retrieval does not fetch the Open Targets function text, so many genes only get association-level claims (`limited`).
- The gene type comes straight from MyGene.info: readthroughs show as `protein-coding`, pseudogenes as `unknown`.
- The PubMed search has no filter, so reviews that only mention a gene in passing are common.
- Non-human studies are not filtered out (e.g. MYOZ3: chicken, rat, horse), and claims do not always name the species.
- Only LLM calls are cached; MyGene, PubMed and Open Targets are called again on every run.
- The judge is an LLM too: it can miss an overstated claim, so `supported` means "the judge found it in the cited text", not "proven".

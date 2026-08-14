# Single-Cell and CRISPR Perturbation Learning Roadmap

## Purpose

This roadmap defines two connected portfolio projects for developing practical experience with modern biotechnology data:

1. **Project #1: Single-Cell Treatment Response Explorer**
2. **Project #2: CRISPR Perturbation Explorer**

The first project teaches the core single-cell data structures, analysis methods, biological concepts, and application architecture needed for the second project.

The long-term objective is not merely to reproduce academic notebooks. It is to build credible, reproducible scientific data products that combine:

- Single-cell biology
- Bioinformatics workflows
- Data engineering
- Scientific metadata modeling
- Reproducibility and lineage
- Interactive analytics
- Evidence-constrained AI agents

---

# Project #1: Single-Cell Treatment Response Explorer

## Project Summary

Build an interactive application that explores how different cell populations respond to a biological or chemical treatment using public single-cell RNA sequencing data.

A recommended first use case is:

> **How do different immune-cell types respond to interferon stimulation?**

The project compares untreated control cells with treated cells and examines the response within each cell type.

```text
Control cells
      vs.
Treated cells
```

This is already a form of perturbation biology. The perturbation is a treatment rather than a genetic edit.

---

## Why This Project Comes First

A single-cell CRISPR experiment combines two major analytical questions:

1. What kind of cell is this?
2. What changed because a particular gene was disrupted?

Project #1 teaches the first question and a simpler version of the second:

1. What kind of cell is this?
2. What changed after treatment?

This removes several complications that appear in CRISPR data:

- Guide RNA assignment
- Multiple perturbations
- Knockout efficiency
- Non-targeting controls
- Guide-level disagreement
- Cells that received a guide but were not effectively perturbed
- Combinatorial perturbations

Once Project #1 is complete, the CRISPR project becomes an extension of a familiar analytical system rather than a completely new domain.

---

## Core Biological Question

For each major cell type:

- How does treatment change gene expression?
- Which genes respond most strongly?
- Which biological pathways become more or less active?
- Do all cell types respond similarly?
- Are some cells apparent nonresponders?
- Could differences be explained by donor, sample, batch, or cell composition?

A strong analysis must distinguish:

> **Changes in cell population composition**

from:

> **Changes in gene expression within the same cell type**

For example, comparing all treated cells against all control cells may produce misleading results if the treated group contains more monocytes and the control group contains more T cells.

The better comparisons are:

```text
Treated monocytes vs. control monocytes
Treated T cells vs. control T cells
Treated B cells vs. control B cells
```

---

## Recommended Data

Use a public single-cell RNA sequencing dataset with:

- A clearly defined treatment
- An untreated or vehicle control
- A manageable number of cells
- Useful sample metadata
- Multiple recognizable cell types
- Preferably multiple biological replicates or donors

### Recommended Initial Scope

- One dataset
- One treatment
- Control and treated groups
- Approximately 5,000 to 30,000 cells
- Four to eight broad cell types
- One tissue or biological system
- One reproducible analysis pipeline

Avoid beginning with:

- Million-cell atlases
- Multiple sequencing modalities
- Spatial transcriptomics
- Complex cancer ecosystems
- Several datasets requiring integration
- Poorly documented academic supplements
- Claims of novel clinical or drug discoveries

A standardized `.h5ad` dataset from a repository such as CZ CELLxGENE is a strong starting point.

---

## Primary Data Structure

Single-cell data is commonly stored in the AnnData format, usually as an `.h5ad` file.

Conceptually, the main expression matrix looks like this:

```text
                    Genes
              G1    G2    G3   ...   G20,000
Cells
Cell 1        0     4     0          7
Cell 2        2     0     1          0
Cell 3        0     9     0          3
...
Cell 30,000
```

Each cell also has metadata such as:

```text
cell_id
sample_id
donor_id
treatment
cell_type
batch
tissue
disease
quality_control_metrics
```

Each gene has metadata such as:

```text
gene_id
gene_symbol
feature_type
```

The matrix is usually sparse because most genes have zero measured expression in any individual cell.

---

## Recommended Technology Stack

### Analysis

- Python
- Jupyter
- Scanpy
- AnnData
- pandas
- NumPy
- SciPy
- statsmodels or another appropriate statistical package

### Application

- Streamlit initially
- Plotly or another interactive visualization library
- FastAPI later if a separate backend becomes useful

### Data Storage

- `.h5ad` for the full sparse expression matrix
- Postgres or DuckDB for metadata and derived analytical results
- Object or file storage for source datasets and generated artifacts

### Engineering

- Git and GitHub
- Docker
- Makefile or task runner
- Automated tests
- Environment lock file
- GitHub Actions
- Structured run metadata and logging

---

## Suggested Architecture

```text
Public .h5ad dataset
        |
        v
Dataset validation
        |
        v
Single-cell preprocessing pipeline
        |
        +------------------------------+
        |                              |
        v                              v
Processed .h5ad                Derived relational results
                                       |
                                       v
                              Postgres or DuckDB
                                       |
                                       v
                              Streamlit application
                                       |
                                       v
                         Optional evidence-constrained agent
```

Do not begin by placing every cell-by-gene value into Postgres.

A dataset containing 30,000 cells and 20,000 genes represents 600 million possible cell-gene combinations. The full sparse matrix belongs in a matrix-oriented format such as AnnData.

Use the relational database for:

- Dataset metadata
- Donors and samples
- Cell metadata
- Analysis runs
- Quality-control summaries
- Cluster assignments
- Cell-type annotations
- Differential-expression results
- Pathway scores
- Provenance and lineage

---

## Suggested Relational Model

### `datasets`

```text
dataset_id
dataset_name
source_url
source_version
organism
tissue
assay_type
downloaded_at
source_checksum
```

### `samples`

```text
sample_id
dataset_id
donor_id
condition
batch
tissue
collection_time
```

### `cells`

```text
cell_id
sample_id
cell_type
cluster_id
total_counts
genes_detected
mitochondrial_fraction
passed_qc
```

### `genes`

```text
gene_id
gene_symbol
feature_type
```

### `analysis_runs`

```text
analysis_run_id
dataset_id
pipeline_version
parameters
package_versions
started_at
completed_at
status
source_checksum
output_checksum
```

### `differential_expression_results`

```text
analysis_run_id
cell_type
condition_a
condition_b
gene_id
log_fold_change
p_value
adjusted_p_value
percent_expressed_a
percent_expressed_b
```

### `pathway_scores`

```text
analysis_run_id
cell_id_or_group_id
pathway_id
pathway_name
score
```

---

## Project Stages

## Stage 1: Dataset Inspection and Validation

Before analysis:

- Load the `.h5ad` file
- Inspect matrix dimensions
- Inspect cell metadata
- Inspect gene metadata
- Count cells by condition, sample, donor, and batch
- Confirm the existence of a valid control group
- Identify missing or inconsistent metadata
- Confirm whether counts are raw, normalized, or transformed
- Record the original dataset checksum and source version

### Deliverable

A dataset profile containing:

- Number of cells
- Number of genes
- Number of donors
- Number of samples
- Treatment groups
- Cell-type labels, if present
- Batch structure
- Missing metadata
- Potential analytical limitations

---

## Stage 2: Quality Control and Preprocessing

Build a reproducible Scanpy pipeline that performs appropriate steps such as:

```text
Load data
  |
  v
Cell and gene quality control
  |
  v
Filtering
  |
  v
Normalization
  |
  v
Log transformation
  |
  v
Highly variable gene selection
  |
  v
Principal-component analysis
  |
  v
Nearest-neighbor graph
  |
  v
UMAP
  |
  v
Clustering
  |
  v
Marker-gene analysis
```

Important concepts to understand:

- Library size
- Genes detected per cell
- Mitochondrial read fraction
- Sparse expression
- Normalization
- Highly variable genes
- Principal components
- Nearest-neighbor graphs
- UMAP
- Clustering
- Marker genes
- Batch effects

### Deliverable

A versioned processing pipeline that can recreate the processed dataset from the original input.

---

## Stage 3: Cell-Type Analysis

If trusted cell-type annotations already exist, validate and use them initially.

If annotations do not exist, use marker genes and reference material to label broad cell populations conservatively.

Prefer broad, defensible categories such as:

- T cells
- B cells
- Monocytes
- Natural killer cells
- Dendritic cells

Avoid making highly specific cell-subtype claims until the underlying biology is understood.

### Questions

- Which cell populations are present?
- Are clusters dominated by treatment, donor, or batch?
- Are known marker genes expressed where expected?
- Do treatment groups contain similar cell-type proportions?
- Are any clusters low-quality or ambiguous?

---

## Stage 4: Treatment Response Analysis

Analyze treatment effects within each cell type.

For every cell type, calculate:

- Number of control cells
- Number of treated cells
- Number of donors or samples represented
- Mean expression by condition
- Differentially expressed genes
- Effect sizes
- Statistical significance
- Adjusted statistical significance
- Percentage of cells expressing each gene
- Relevant pathway or gene-set scores

### Important Statistical Caveat

Cells from the same donor or sample are not necessarily independent biological replicates.

A naive cell-level test may produce extremely small p-values because thousands of cells are treated as independent observations.

As the project matures, investigate:

- Pseudobulk aggregation
- Donor-aware comparisons
- Sample-level replication
- Mixed models
- Batch-aware methods

The initial application may display simpler results, but it should clearly document the experimental unit and limitations.

---

## Stage 5: Interactive Application

Build a Streamlit application with the following pages.

### Dataset Overview

- Dataset source
- Number of cells
- Number of genes
- Number of samples
- Number of donors
- Treatment groups
- Cell-type composition
- Quality-control summaries
- Known limitations

### Cell Map

- Interactive UMAP
- Color by cell type
- Color by treatment
- Color by donor
- Color by sample
- Color by batch
- Color by expression of a selected gene

### Treatment Comparison

Allow the user to select:

- Cell type
- Control condition
- Treatment condition

Display:

- Differential-expression table
- Effect-size ranking
- Volcano plot
- Gene-expression distributions
- Percent-expressing comparisons
- Pathway scores
- Number of biological replicates

### Gene Explorer

Allow the user to search for a gene and view:

- Expression by cell type
- Expression by treatment
- Percent of cells expressing the gene
- Distribution across donors or samples
- Related differential-expression results
- Plain-language gene description, if available

### Methodology and Provenance

Display:

- Dataset source
- Dataset version
- Processing steps
- Filtering thresholds
- Pipeline version
- Package versions
- Analysis timestamp
- Source and output checksums
- Limitations

---

## Stage 6: Evidence-Constrained Agent

Add an agent only after the deterministic analysis and data model work correctly.

Example questions:

- Which cell type responded most strongly to treatment?
- What happened to `IFIT1` expression in monocytes?
- Which genes responded across every major immune-cell type?
- Which responses were unique to monocytes?
- Could donor composition explain this apparent effect?
- Which results are statistically significant but have small effect sizes?
- Show the evidence behind that conclusion.

### Agent Design

```text
User question
      |
      v
Resolve entities
- gene
- cell type
- treatment
- comparison
- metric
      |
      v
Build constrained analysis plan
      |
      v
Query governed derived results
      |
      v
Return answer with evidence and caveats
```

The agent should not freely infer scientific conclusions from the raw expression matrix.

It should use precomputed, governed results and return:

- The comparison performed
- Effect size
- Statistical evidence
- Replicate counts
- Source dataset
- Analysis run
- Important caveats

---

## Project #1 Success Criteria

Project #1 is complete when you can confidently explain and demonstrate:

- What a single-cell expression matrix represents
- How AnnData organizes matrices and metadata
- Why single-cell matrices are sparse
- What quality-control filtering does
- What normalization does
- How cells are clustered
- How cell types are identified
- Why UMAP can be useful and misleading
- How treatment response differs by cell type
- Why biological replicates matter
- How batch and donor effects can create misleading conclusions
- Why full matrix data and relational metadata need different storage patterns
- How to reproduce an analysis from source data and recorded parameters

---

# Project #2: CRISPR Perturbation Explorer

## Project Summary

Extend the single-cell treatment-response platform to analyze single-cell CRISPR perturbation data.

Instead of comparing only treatment against control, compare cells carrying different genetic perturbations.

```text
Non-targeting control
        vs.
Gene knockout or knockdown
```

Example perturbations in an interferon-response system might include:

```text
Non-targeting control
STAT1 disruption
IRF9 disruption
JAK1 disruption
IFNAR1 disruption
```

The objective is to investigate how changing a gene alters cellular state and pathway response.

---

## Core Biological Questions

- Does disrupting a gene change the expected cellular response?
- Which perturbations produce similar expression profiles?
- Which genes appear to regulate the same downstream program?
- Which perturbations affect only particular cell types?
- Do multiple guide RNAs targeting the same gene agree?
- Which assigned cells appear not to have been effectively perturbed?
- Which perturbations change cell state, viability, or composition?
- Which gene disruptions block or amplify a treatment response?
- Are observed effects reproducible across samples or donors?

---

## How Project #2 Extends Project #1

| Project #1 | Project #2 |
|---|---|
| Untreated vs. treated | Non-targeting guide vs. targeted guide |
| One or a few conditions | Many possible target genes |
| Treatment label per cell | Guide RNA assignment per cell |
| Treatment-effect estimation | Perturbation-effect estimation |
| Cell-type-specific response | Cell-type-specific knockout response |
| Donor and batch effects | Donor, batch, guide, and perturbation effects |
| Responders and nonresponders | Effective and ineffective perturbations |
| Differential expression | Perturbation signatures and similarity |
| Pathway activation | Regulatory and causal pathway hypotheses |

Most of the Project #1 stack remains useful:

- AnnData
- Scanpy
- Sparse matrices
- Cell metadata
- Cell-type analysis
- Differential expression
- Pathway scoring
- UMAP
- Reproducible pipelines
- Derived relational results
- Streamlit
- Evidence-constrained agent architecture

---

## New Data Entities

Add entities such as:

### `guide_rnas`

```text
guide_id
guide_sequence
target_gene_id
guide_type
library_name
```

### `guide_assignments`

```text
cell_id
guide_id
assignment_confidence
guide_count
assignment_method
```

### `perturbations`

```text
perturbation_id
target_gene_id
perturbation_type
control_type
```

### `cell_perturbations`

```text
cell_id
perturbation_id
guide_id
assignment_confidence
estimated_effective
```

### `perturbation_signatures`

```text
analysis_run_id
perturbation_id
cell_type
gene_id
effect_size
p_value
adjusted_p_value
```

### `perturbation_similarity`

```text
analysis_run_id
perturbation_a
perturbation_b
cell_type
similarity_metric
similarity_value
```

### `guide_concordance`

```text
analysis_run_id
target_gene_id
guide_a
guide_b
concordance_metric
concordance_value
```

---

## Additional Analytical Challenges

## Guide Assignment

A cell may contain:

- No detected guide
- One guide
- Multiple guides
- An uncertain guide assignment
- Ambient guide RNA contamination

The project must define clear rules for:

- Accepted assignments
- Multiplets
- Low-confidence cells
- Non-targeting controls
- Combinatorial perturbations

---

## Perturbation Effectiveness

Receiving a guide does not guarantee that the target gene was successfully disrupted.

Possible reasons include:

- Inefficient editing
- Incomplete knockdown
- Low target-gene expression
- Biological compensation
- Incorrect guide assignment
- Technical noise

The analysis should distinguish:

> **Guide detected**

from:

> **Cell appears biologically perturbed**

This is a key reason CRISPR perturbation analysis is more complex than ordinary treatment-response analysis.

---

## Guide-Level Agreement

Multiple guide RNAs may target the same gene.

A strong target-level conclusion should examine:

- Whether guides produce similar expression effects
- Whether one guide behaves anomalously
- Whether the target-gene effect is reproducible
- Whether guide-specific toxicity is present

Do not automatically aggregate all guides without checking concordance.

---

## Control Selection

Useful controls may include:

- Non-targeting guides
- Safe-targeting guides
- Mock-treated cells
- Unperturbed cells
- Positive-control perturbations

The application should clearly identify which control was used for every comparison.

---

## Perturbation Signatures

For every perturbation, calculate a response signature such as:

- Differentially expressed genes
- Pathway changes
- Latent embedding shift
- Cell-state shift
- Similarity to other perturbations
- Distance from control cells
- Cell-type-specific effect

These signatures allow questions such as:

- Which knockouts produce similar cellular states?
- Which genes may participate in the same pathway?
- Which perturbations reverse or amplify treatment response?
- Which perturbations have broad versus cell-type-specific effects?

---

## Recommended Tooling

Retain:

- Python
- Scanpy
- AnnData
- pandas
- NumPy
- Streamlit
- Postgres or DuckDB
- Docker
- GitHub Actions

Add as appropriate:

- Pertpy
- CRISPR-specific assignment or quality-control tools
- Pseudobulk or donor-aware statistical methods
- Embedding and perturbation-similarity methods
- Gene-set and pathway databases

Avoid beginning with advanced foundation-model training.

The initial value should come from:

- Correct data modeling
- Reproducible processing
- Clear control definitions
- Guide and perturbation quality checks
- Transparent analysis
- Evidence-backed exploration

---

## Project #2 Application Pages

## Perturbation Overview

- Number of cells
- Number of perturbations
- Number of guides
- Control types
- Cells per guide
- Cells per target gene
- Guide-assignment confidence
- Multiplet rates
- Unassigned-cell rates

## Perturbation Map

- UMAP colored by perturbation
- UMAP colored by target gene
- UMAP colored by guide
- UMAP colored by cell type
- UMAP colored by perturbation confidence
- UMAP colored by pathway score

## Perturbation Comparison

Allow the user to select:

- Target gene or guide
- Control group
- Cell type
- Sample or donor subset

Display:

- Differential-expression results
- Effect-size rankings
- Pathway changes
- Expression distributions
- Replicate counts
- Perturbation-effect confidence

## Perturbation Similarity

Display:

- Similarity matrix
- Hierarchical grouping of perturbations
- Shared response genes
- Shared pathway changes
- Cell-type-specific similarity
- Guide-level versus gene-level results

## Guide Quality

Display:

- Guides per target
- Cells per guide
- Assignment confidence
- Guide concordance
- Outlier guides
- Estimated perturbation effectiveness
- Possible guide-specific toxicity

## Gene and Pathway Explorer

Allow investigation of:

- Target genes
- Downstream response genes
- Pathways
- Cell types
- Perturbations affecting a selected pathway
- Perturbations with similar signatures

## Provenance and Methodology

Display:

- Dataset source
- Guide library
- Reference genome
- Assignment method
- Filtering rules
- Control definitions
- Pipeline version
- Package versions
- Statistical method
- Known limitations

---

## Project #2 Agent Questions

Example questions:

- Which perturbations most strongly reduced the interferon-response program?
- Did all guides targeting `STAT1` produce similar effects?
- Which cells assigned to the `JAK1` perturbation still resemble controls?
- Which knockouts produced similar transcriptional responses?
- Which perturbations affected monocytes but not T cells?
- Which targets have strong effects but poor guide concordance?
- Which perturbations altered cell-state composition?
- What evidence supports the conclusion that `IRF9` is required for this response?
- Which result is most sensitive to control selection?
- Show the exact comparison and analysis run behind this answer.

The agent should always distinguish:

- Association
- Experimental perturbation
- Estimated causal interpretation
- Technical uncertainty
- Biological replication

---

## Project #2 Success Criteria

Project #2 is complete when you can explain and demonstrate:

- How CRISPR perturbations are represented in single-cell data
- How guide assignments are attached to cells
- Why guide detection does not guarantee effective perturbation
- Why non-targeting controls are important
- How multiple guides targeting the same gene should be evaluated
- How perturbation effects are estimated within a cell type
- How perturbation signatures can be compared
- How batch, donor, guide, and cell-state effects can confound results
- How treatment and CRISPR perturbations can be analyzed together
- How to return reproducible, evidence-backed conclusions

---

# Recommended Development Sequence

## Phase 0: Preparation

Before Project #1:

- Complete approximately 10 introductory Rosalind problems
- Learn basic DNA, RNA, gene, protein, transcription, and translation concepts
- Complete a Scanpy beginner tutorial
- Learn the basic AnnData object structure
- Become comfortable reading single-cell metadata

---

## Phase 1: Project #1 Minimum Viable Analysis

- Select one manageable public dataset
- Profile the dataset and metadata
- Build the preprocessing pipeline
- Reproduce cell clusters and broad cell types
- Compare treatment and control within cell types
- Export differential-expression results
- Record full analysis provenance

---

## Phase 2: Project #1 Productization

- Create relational metadata tables
- Store derived analytical results
- Build the Streamlit interface
- Add dataset, cell-map, comparison, and gene pages
- Add reproducibility documentation
- Add automated validation and tests

---

## Phase 3: Project #1 Agent

- Define supported analytical questions
- Build entity resolution for genes, cell types, and treatments
- Build a typed analysis plan
- Query governed results
- Return evidence, provenance, and caveats
- Evaluate answers against benchmark questions

---

## Phase 4: Project #2 Minimum Viable Analysis

- Select one modest public CRISPR single-cell dataset
- Inspect guide and perturbation metadata
- Define control groups
- Validate guide assignments
- Compare one or a few perturbations with controls
- Measure guide concordance
- Produce perturbation signatures

---

## Phase 5: Project #2 Productization

- Extend the data model
- Add perturbation-specific application pages
- Add guide-quality views
- Add perturbation-similarity analysis
- Add evidence-constrained agent capabilities
- Document assumptions and limitations

---

# Scope Guardrails

## Do

- Start with one well-documented dataset
- Prefer clear experimental designs
- Preserve raw source files
- Record versions and checksums
- Treat donor and sample as potential experimental units
- Use broad cell-type labels initially
- Compare conditions within cell type
- Display effect sizes, not only p-values
- Clearly identify controls
- Keep the full matrix in AnnData
- Store derived results relationally
- Document uncertainty
- Reproduce results from code

## Do Not

- Claim clinical validity
- Claim a novel drug target based on one public dataset
- Treat every cell as an independent biological replicate
- Interpret UMAP distance as a formal quantitative effect
- Aggregate different cell types without justification
- Ignore batch or donor composition
- Assume every detected guide caused an effective perturbation
- Aggregate guides without checking agreement
- Build an unconstrained LLM directly over the raw matrix
- Begin with a million-cell dataset
- Train a large biological foundation model as the first objective

---

# Final Portfolio Narrative

Together, the two projects tell a coherent story:

> I built a reproducible single-cell analytics platform that models cells, samples, conditions, genes, analysis runs, and treatment-response results. I then extended the platform to support CRISPR perturbation experiments, including guide assignment, control selection, perturbation quality, guide concordance, cell-type-specific effects, and evidence-backed natural-language exploration.

This demonstrates experience with:

- Modern biotechnology data
- Single-cell RNA sequencing
- CRISPR perturbation data
- Scientific metadata
- Matrix and relational data architecture
- Reproducibility
- Statistical reasoning
- Data quality
- Interactive scientific software
- Semantic modeling
- AI-agent constraints
- Evidence and provenance

The projects are valuable even if they do not lead directly to a biotech role. They also strengthen general skills in scientific computing, data platforms, reproducible analytics, and trustworthy AI systems.

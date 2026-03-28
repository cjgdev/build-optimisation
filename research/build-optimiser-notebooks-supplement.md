# Build Optimiser — Supplement: Revised Analysis Notebooks

## Overview

This document replaces the analysis notebook specification from the original technical document. The project goals have expanded from build time optimisation alone to a dual objective: improving build times AND restructuring the codebase into selectable feature groups so that developers can disable compilation of areas they don't work in.

The analysis tells a four-part story:

1. **Current State** — global view of codebase health, build time distribution, and coupling.
2. **Build Performance Optimisation** — where time is spent and what to do about it.
3. **Modularity Optimisation** — discovering feature groups, optimising their boundaries, and identifying structural changes to reduce cross-group coupling.
4. **Conclusion and Recommendations** — a unified, sequenced action plan with ROI estimates.

This document specifies the complete notebook list, detailed tasks and techniques for each, additional data collection requirements, new shared library functions, and additional Python dependencies.

---

## 1. Additional Data Collection Requirements

The revised analysis requires additional data beyond what the existing collection scripts produce. These are collected by modifying existing scripts or adding lightweight post-processing — no new build passes are needed.

### 1.1 Contributor-File Commit Matrix

**Source:** Git history (already collected by the git history script).

**Change to `scripts/collect/06_git_history.py`:** In addition to the per-file commit count, also collect per-contributor-per-file commit counts.

Run:
```bash
git -C <source_dir> log \
  --since="<git_history_months> months ago" \
  --pretty=format:"%H %ae" \
  --name-only \
  -- '*.cpp' '*.cc' '*.cxx' '*.h' '*.hpp' '*.hxx'
```

This produces commit hash + author email on one line, followed by changed file names. Parse into per-contributor-per-file commit counts.

**Additional output:** `data/raw/contributor_file_commits.csv`

| Column | Type | Description |
|---|---|---|
| `contributor` | str | Author email address |
| `source_file` | str | File path (relative to repo root) |
| `commit_count` | int | Number of commits by this contributor to this file in the window |

Also output a contributor summary: `data/raw/contributors.csv`

| Column | Type | Description |
|---|---|---|
| `contributor` | str | Author email address |
| `total_commits` | int | Total commits in the window |
| `first_commit_date` | str | Earliest commit date in the window |
| `last_commit_date` | str | Most recent commit date in the window |
| `files_touched` | int | Number of distinct files touched |

### 1.2 Executable Target Identification

**Source:** Dependency graph dot files (already collected) and `build.ninja`.

**Change to `scripts/consolidate/build_target_metrics.py`:** Add a `target_type` column to the target metrics DataFrame. Values: `executable`, `shared_library`, `static_library`, `object_library`, `interface_library`, `custom_target`, `unknown`.

This can be determined from:
- The dot files — CMake's graphviz output uses different node shapes for executables vs libraries.
- `build.ninja` — link rules differ: executables use `CXX_EXECUTABLE_LINKER` rules, shared libraries use `CXX_SHARED_LIBRARY_LINKER`, etc.
- `CMakeCache.txt` or the CMake file API if available.

**New column in `data/processed/target_metrics.parquet`:**

| Column | Type | Description |
|---|---|---|
| `target_type` | str | One of: `executable`, `shared_library`, `static_library`, `object_library`, `interface_library`, `custom_target`, `unknown` |

### 1.3 Executable-Library Dependency Matrix

**Source:** Dependency graph (already collected).

**Produced during consolidation or in notebook 05.** For each executable target, compute the full transitive dependency closure using the dependency graph. Produce a binary matrix where rows are executables and columns are library targets.

**New output:** `data/processed/exe_library_matrix.parquet`

A DataFrame with columns:
| Column | Type | Description |
|---|---|---|
| `executable` | str | Executable target name |
| `library` | str | Library target name |
| `is_direct` | bool | True if this is a direct dependency, False if transitive only |

This is stored as an edge list (long format) rather than a wide matrix for storage efficiency. It can be pivoted to a wide binary matrix in notebooks as needed.

### 1.4 Contributor-Target Commit Matrix

**Produced during consolidation.** Join `contributor_file_commits.csv` with the file-to-target mapping to produce per-contributor-per-target commit counts.

**New output:** `data/processed/contributor_target_commits.parquet`

| Column | Type | Description |
|---|---|---|
| `contributor` | str | Author email address |
| `cmake_target` | str | Target name |
| `commit_count` | int | Number of commits by this contributor to files in this target |

---

## 2. Revised Notebook List

| # | Notebook | Story Part |
|---|---|---|
| 01 | Data Cleaning | Prerequisite |
| 02 | Contributor Groups and Code Ownership | Prerequisite |
| 03 | Global Codebase Health | Part 1: Current State |
| 04 | Build Performance Analysis | Part 2: Build Performance |
| 05 | Executable Dependency Analysis | Part 3: Modularity |
| 06 | Feature Group Discovery | Part 3: Modularity |
| 07 | Feature Group Optimisation | Part 3: Modularity |
| 08 | Impact Simulation | Part 3: Modularity |
| 09 | Recommendations | Part 4: Conclusion |

All notebooks share a common data loading preamble: read the Parquet files from `data/processed/`, load the dependency graph with `graph.py`, and attach metrics as node attributes.

---

## 3. Notebook Specifications

### 3.1 Notebook 01 — Data Cleaning

**Purpose:** Validate, clean, and prepare all datasets for analysis.

**Tasks:**

**Missing data identification.** Identify targets with missing compile times — header-only libraries, interface targets, and imported targets will have no compile time. Decide per case whether to exclude from build time analysis (interface targets) or fill with zero (header-only libraries with no source files). Document decisions.

**Outlier detection.** Flag files with anomalous compile times caused by build machine load, swapping, or thermal throttling. Use IQR method: any file with compile time above Q3 + 1.5×IQR is flagged. Visualise the flagged outliers on a scatter plot of compile time vs SLOC before deciding whether to clip, remove, or keep them. For time-based analyses (critical path, incremental simulation), outliers should be clipped to the IQR fence rather than removed, to avoid underestimating build times.

**Path alignment.** Canonicalise all file paths across datasets. Git history uses repo-relative paths, compile_commands.json uses absolute paths, and the codegen inventory may use build-tree-relative paths. Create a canonical mapping and verify that all files from each dataset can be joined. Report any files present in one dataset but not another.

**Target validation.** Cross-reference the target list from the dot files with targets found in the build tree (from object files and compile_commands.json). Identify and report:
- Phantom targets: in the graph but not built (possibly conditional targets that were disabled).
- Unlisted targets: built but not in the graph (possibly added after the graphviz configure).
- Alias targets: targets that are just aliases for other targets.

**Codegen validation.** Review entries classified as `unknown_codegen`. Validate generator-to-file mappings. Check for generated files not in the file metrics and vice versa. See the codegen supplement for full details.

**Contributor data validation.** Check for contributor aliases — the same person committing under different email addresses. Look for email addresses that differ only in domain (e.g. `jane@company.com` vs `jane.doe@company.com`). Build an alias mapping (can be manual or heuristic-based) and merge commit counts. Flag bot accounts and CI commits (e.g. email addresses containing "bot", "ci", "jenkins", "buildbot") for exclusion from contributor analysis.

**Type casting and normalisation.** Ensure all columns have correct types. Normalise all time values to milliseconds. Normalise all sizes to bytes.

**Output:** Cleaned versions of all Parquet files in `data/processed/`. A cleaning log summarising rows removed, modified, or flagged.

---

### 3.2 Notebook 02 — Contributor Groups and Code Ownership

**Purpose:** Identify groups of contributors who work on the same areas of the codebase, and map code ownership to targets. This notebook produces data consumed by almost every subsequent notebook.

#### Task 1: Contributor Clustering

**Input:** `contributor_target_commits.parquet`, `contributors.csv`.

**Step 1 — Build the contributor-target matrix.** Create a matrix where rows are contributors and columns are targets. Values are commit counts. Filter out contributors with fewer than N commits (e.g. 10) to exclude drive-by contributors who would add noise. Filter out targets with fewer than M commits (e.g. 5) to exclude rarely-touched targets.

**Step 2 — Normalise.** Convert each contributor's row to a probability distribution over targets (divide by row sum). This ensures that prolific contributors don't dominate the clustering just by volume. A contributor who made 500 commits across 50 targets should cluster the same way as one who made 50 commits across the same 50 targets in the same proportions.

**Step 3 — Clustering.** Apply multiple methods and compare:

- **Hierarchical clustering (Ward linkage):** Compute pairwise distances between contributor vectors using Jensen-Shannon divergence (appropriate for probability distributions). Build a dendrogram. Cut at different levels to explore team structure at different granularities. Ward linkage minimises within-cluster variance.

- **Non-negative Matrix Factorisation (NMF):** Decompose the contributor-target matrix (pre-normalisation, raw counts) into two matrices: W (contributors × K latent groups) and H (K latent groups × targets). Each contributor has a soft assignment across K groups. Each group has a profile over targets. Sweep K from 3 to 15 and evaluate reconstruction error and silhouette score to choose the best K. NMF is preferred over PCA here because commit counts are non-negative and NMF produces interpretable parts-based decompositions.

- **Bipartite community detection:** Build a bipartite graph with contributor nodes and target nodes, weighted by commit counts. Project to a contributor-contributor graph where edge weight between two contributors is the number of shared targets (weighted by commit overlap). Run Louvain community detection on the projected graph.

**Step 4 — Consensus.** Compare the three methods. Use Adjusted Rand Index (ARI) to measure agreement between clusterings. If all three agree, the groups are robust. If they disagree, examine the points of disagreement — these are contributors who work across team boundaries.

**Step 5 — Labelling.** For each identified group, examine the targets they most contribute to. Assign a descriptive label based on the functional area (e.g. "clearing engine team", "gateway team", "market data team"). This labelling is manual and domain-knowledge-driven but the notebook should surface the information needed to do it: top 10 targets per group ranked by that group's commit share.

#### Task 2: Code Ownership Mapping

**Input:** Contributor groups from Task 1, `contributor_target_commits.parquet`.

**Step 1 — Ownership scoring.** For each target, compute an ownership score per contributor group. The score is the fraction of recent commits from members of that group, weighted by recency. Use exponential time decay with a configurable half-life (default: 3 months). Formula:

```
score(target, group) = Σ exp(-λ × age_days) for each commit to target by a group member
```

Where `λ = ln(2) / half_life_days`.

Normalise scores per target so they sum to 1. The group with the highest normalised score is the primary owner.

**Step 2 — Ownership concentration.** For each target, compute the Herfindahl-Hirschman Index (HHI) of the ownership scores: `HHI = Σ score_i²`. HHI near 1 means one group dominates (clear ownership). HHI near 1/K means ownership is evenly split (contested). Flag targets with HHI below a threshold (e.g. 0.5) as "contested" — these are targets where no single team clearly owns the code.

**Step 3 — Bus factor.** For each target, count the number of contributors from the owning group who have committed in the last 3 months. A bus factor of 1 means only one person is actively maintaining it. Flag targets with bus factor ≤ 1 as knowledge risks.

**Step 4 — Cross-team dependency map.** Using the dependency graph and ownership mapping, identify every edge where the source and destination targets have different owning groups. These are cross-team dependencies. Compute a team-level dependency summary: "Team A depends on N targets owned by Team B." Visualise as a chord diagram or directed graph at the team level.

**Output:**

Save `data/processed/contributor_groups.parquet`:

| Column | Type | Description |
|---|---|---|
| `contributor` | str | Author email |
| `group_id` | int | Assigned group ID |
| `group_label` | str | Descriptive label (filled after manual review) |
| `group_score` | float | Soft assignment strength (from NMF) |

Save `data/processed/target_ownership.parquet`:

| Column | Type | Description |
|---|---|---|
| `cmake_target` | str | Target name |
| `owning_group_id` | int | Primary owning group |
| `owning_group_label` | str | Group label |
| `ownership_hhi` | float | Ownership concentration (0–1) |
| `bus_factor` | int | Active contributors from owning group |
| `is_contested` | bool | True if HHI < threshold |

These are consumed by notebooks 03–09.

---

### 3.3 Notebook 03 — Global Codebase Health

**Purpose:** Establish the current state of the codebase using quantifiable metrics. This is Part 1 of the story — making the case that improvements are needed.

#### Task 1: Modularity Score

Compute Newman's modularity coefficient (Q) for the dependency graph using the community structure from Louvain/Leiden community detection on the undirected version of the DAG. Report the score and contextualise it: well-structured modular codebases typically score above 0.5; tightly coupled monoliths score below 0.3.

Also compute Q using the contributor-group ownership as the partition (rather than Louvain-detected communities). This measures how well the architecture aligns with the organisational structure. If the Louvain partition has higher Q than the ownership partition, the codebase has natural structure that doesn't match team boundaries.

#### Task 2: Coupling Metrics

For each target, compute:

- **Afferent coupling (Ca):** Number of targets that depend on this target (in-degree in the dependency DAG, including transitive).
- **Efferent coupling (Ce):** Number of targets this target depends on (out-degree, including transitive).
- **Instability (I):** `Ce / (Ca + Ce)`. Ranges from 0 (maximally stable — depended on by everything, depends on nothing) to 1 (maximally unstable — depends on everything, depended on by nothing).
- **Abstractness (A):** Fraction of the target's public API that is interface-only (header-only, pure virtual classes). This is harder to compute precisely; approximate as `header_file_count / (header_file_count + source_file_count)` or, if available, use the interface vs implementation distinction from CMake target types.
- **Distance from main sequence (D):** `|A + I - 1|`. Targets on the "main sequence" (A + I = 1) have a good balance of stability and abstractness. Targets far from it are in the "zone of pain" (concrete and stable — hard to change) or the "zone of uselessness" (abstract and unstable — over-engineered).

Plot all targets on the A-I plane. Annotate with target names for those in the zone of pain (top-left: low I, low A). These are the targets that are both heavily depended upon and concrete — they resist change and cause pain when changed.

#### Task 3: Build Time Decomposition

**Treemap or Sankey diagram** showing:
- Level 1: Total build time split into compilation vs linking.
- Level 2: Compilation time split by target (top 20 targets, remainder grouped as "other").
- Level 3: Within high-cost targets, split by generated vs hand-written code.

**Pareto chart:** Cumulative compile time vs target rank (sorted descending by compile time). Annotate the 80% line — "N targets account for 80% of build time."

**Per-team build time share:** Stacked bar chart showing each contributor group's share of total compile time (based on ownership). This frames build time as a team responsibility.

#### Task 4: Dependency Structure Profile

**DAG depth histogram:** Number of targets at each topological depth level. Overlaid with total compile time at each depth. Deep levels with high compile time are serial bottlenecks.

**DAG width at each depth:** Maximum parallelism available at each build stage. Plot alongside the actual number of Ninja jobs — if the width exceeds available cores, parallelism is not the constraint.

**Degree distribution:** In-degree and out-degree histograms. A power-law-like distribution (few targets with very high degree, many with low degree) indicates hub targets that are structural bottlenecks.

**Cross-team dependency summary:** From notebook 02's cross-team dependency map, compute the total number of cross-team edges and the fraction of all edges that cross team boundaries. A high fraction indicates poor alignment between architecture and organisation.

#### Task 5: Summary Dashboard

Produce a single-page summary with the key metrics:
- Modularity score (Q)
- Number of targets, edges, and graph density
- 80/20 ratio (how many targets account for 80% of build time)
- Full build time (wall clock with maximum parallelism)
- Mean and median incremental rebuild time (from git history simulation — preview of notebook 04)
- Cross-team dependency fraction
- Number of contested targets (HHI < 0.5)

Save this as a table in `data/results/codebase_health_summary.csv`.

---

### 3.4 Notebook 04 — Build Performance Analysis

**Purpose:** Deep dive into build performance — where time is spent, why, and what would improve it. This is Part 2 of the story.

#### Task 1: Critical Path Analysis

Compute the critical path through the DAG weighted by per-target compile time. Use `nx.dag_longest_path` with weight attribute. The critical path length is the theoretical minimum full build time with infinite parallelism.

For each target, compute slack: `critical_path_length - longest_path_through(target)`. Targets with zero slack are on the critical path. Targets with low slack are near-critical — they would become critical if they got slightly slower.

Annotate the critical path with:
- Owning team per target.
- Generated code fraction per target.
- Codegen type (protobuf, bison, etc.) per target where relevant.

If the critical path passes through targets owned by multiple teams, flag this as a coordination requirement.

Visualise the DAG with critical path highlighted. Use Graphviz with critical path nodes in red, near-critical (slack < 10% of critical path) in orange, and all others in grey.

#### Task 2: Rebuild Amplification Analysis

For each historical commit in the git window:
1. Identify the set of directly modified targets (targets containing the changed files).
2. Compute the set of targets that would need to rebuild (transitive dependants of modified targets).
3. Compute the rebuild amplification factor: `|rebuild set| / |change set|`.
4. Compute the rebuild time: sum of compile times for the rebuild set (or simulate parallel build with N cores).

Plot the distribution of rebuild amplification factors across all commits. Compute the mean, median, P90, and P99. A P90 amplification factor of 15 means "90% of the time, a single-target change triggers rebuilds in 15 or fewer targets."

Break down by owning team: for commits by team A, what is the typical rebuild amplification? Which team's changes have the widest blast radius?

Compute cross-team rebuild impact: for commits by team A, how much rebuild time falls on targets owned by other teams? Sum and rank. "Team A's changes caused an estimated X hours of cross-team rebuild time over the past 12 months."

#### Task 3: Incremental Build Simulation

Simulate the actual developer experience of incremental builds.

For each historical commit:
1. Identify the rebuild set (as in Task 2).
2. Simulate a parallel build of the rebuild set using the DAG structure. Model a Ninja-like scheduler with N cores (use the `ninja_jobs` config value). Walk the DAG in topological order; at each step, schedule up to N ready targets in parallel, advancing the clock by the compile time of the longest target in the current batch.
3. Record the simulated wall-clock incremental build time.

Plot the distribution of incremental build times. Report mean, median, P90. "The median incremental build takes X seconds. The P90 is Y seconds."

Compare against a hypothetical "perfect modularity" baseline: if developers could build only their team's targets, what would the incremental build time be? (Use the ownership data to restrict the rebuild set to same-team targets.) The gap between current and ideal is the motivation for modularity work.

#### Task 4: Bottleneck Regression

Build a regression model predicting per-file compile time from available features:
- `code_lines` (SLOC)
- `preprocessed_bytes` (preprocessor output size)
- `header_max_depth` (include depth)
- `total_includes` (total include count)
- `unique_headers` (unique header count)
- `object_size_bytes` (output size)
- `is_generated` (binary: generated vs hand-written)
- `generator` (categorical: which generator, or "none")

Use a Random Forest or Gradient Boosted Trees (scikit-learn `GradientBoostingRegressor`) for the model. Tree-based models handle non-linearities and interactions well. Compute feature importances via permutation importance to rank which factors most strongly predict compile time.

Report the top factors. For example: "preprocessed size explains 45% of compile time variance; header depth explains 20%; generated code is 30% slower per SLOC than hand-written code."

For each of the top factors, estimate the potential time saving. For example: "if all files with preprocessed size above the P75 threshold were reduced to P75, total compile time would decrease by X%." This uses the regression model for counterfactual prediction.

#### Task 5: Codegen Build Impact

From the codegen supplement: summary table of generators, generated file counts, compile times, and share of overall build. Scatter plot of generated compile fraction vs target compile time. Box plots of compile time per SLOC for generated vs hand-written code by generator type.

Identify targets on the critical path where generated code dominates compile time. For these targets, the recommendation is generator-level optimisation (protobuf lite, schema splitting, generator output tuning) rather than library restructuring.

---

### 3.5 Notebook 05 — Executable Dependency Analysis

**Purpose:** Understand how executable targets consume the library graph. This is the foundation for feature group discovery.

#### Task 1: Dependency Closure Computation

For each executable target in the dependency graph, compute the full transitive dependency closure — every library target it needs to build. Store as the executable-library dependency matrix (`exe_library_matrix.parquet` described in section 1.3).

Report basic statistics:
- Distribution of dependency closure sizes (how many libraries each executable needs).
- The largest closures — executables that pull in the most libraries.
- The most-depended-on libraries — libraries that appear in the most executable closures.

#### Task 2: Jaccard Similarity Between Executables

Compute pairwise Jaccard similarity between all executable dependency closures. `Jaccard(A, B) = |A ∩ B| / |A ∪ B|`, where A and B are the library sets of two executables.

Build a similarity matrix and visualise as a clustered heatmap (hierarchical clustering on both axes). Executables with high Jaccard similarity share most of their dependencies and are natural candidates for grouping into the same feature.

#### Task 3: Core Library Identification

Identify libraries that appear in the dependency closure of nearly every executable. These are "core" libraries that will be needed regardless of which features are enabled.

Compute the appearance frequency of each library: `freq = (number of executables that depend on it) / (total executables)`. Libraries with frequency above a threshold (e.g. 0.8) are core. Plot the frequency distribution — there will typically be a gap between "appears everywhere" and "appears in a few executables" that defines a natural threshold.

Label core libraries. These will form the "always-on" base layer in the feature group structure.

#### Task 4: Thin Dependency Detection

For each dependency edge from an executable's closure to a library in a different anticipated feature group, assess the "thinness" of the dependency.

**Method 1 — Header inclusion analysis.** Using the `-H` data from the header depth collection, count how many headers from the dependency library are actually included (directly or transitively) by files in the depending target. A dependency where only 2 out of 200 headers are included is thin.

**Method 2 — Build impact analysis.** If the depended-on library is removed from the executable's dependency list and the build attempted, how many compilation errors result? This is a more aggressive approach and may not be practical in a notebook — better as a recommendation for manual investigation.

For each thin dependency, record:
- The depending executable/library.
- The depended-on library.
- The number of headers actually used (from method 1).
- The total public headers in the depended-on library.
- The "thinness ratio": used headers / total headers.

Thin dependencies are prime candidates for interface extraction — pulling the small set of needed functionality into a lightweight interface target in the core group.

**Output:** Save thin dependency data to `data/results/thin_dependencies.csv`.

#### Task 5: Executable Grouping Preview

Using the Jaccard similarity matrix from Task 2, apply hierarchical clustering to group executables. Cut the dendrogram at different levels and examine the resulting groups. For each candidate grouping, report:
- Number of executable groups.
- For each group: the executables in it, the union of their dependency closures, and the closure size.
- Cross-group library overlap: libraries that appear in multiple executable groups (beyond core).

This is a preview of the feature group structure. The actual feature groups are refined in notebook 06.

---

### 3.6 Notebook 06 — Feature Group Discovery

**Purpose:** Discover the optimal feature group structure — a partition of library targets into groups that can be independently enabled or disabled.

#### Task 1: Biclustering

Apply spectral co-clustering (`sklearn.cluster.SpectralCoclustering`) to the executable-library dependency matrix (binary, with core libraries removed — they're in every group by definition).

Spectral co-clustering simultaneously groups rows (executables) and columns (libraries) such that executables in the same bicluster depend on the same set of libraries, and libraries in the same bicluster are used by the same set of executables. This produces candidate feature groups where each group is a set of libraries and a set of executables that use them.

Sweep the number of biclusters from 3 to 12. For each K, compute:
- The fraction of the matrix covered by within-bicluster 1s vs cross-bicluster 1s. Higher within-bicluster density means the groups are more self-contained.
- The reconstruction error.

Choose K that balances group count against cross-group dependency leakage.

#### Task 2: Hierarchical Community Detection

As a complementary approach, apply hierarchical community detection to the library dependency subgraph (excluding core libraries).

**Step 1:** Run Leiden community detection with varying resolution parameters. At low resolution, you get a few large communities. At high resolution, you get many small communities.

**Step 2:** Build a community dendrogram by running Leiden at multiple resolutions and tracking how communities split as resolution increases. This gives a hierarchical view: 3–4 top-level feature groups that subdivide into 8–12 sub-features.

**Step 3:** At each level of the hierarchy, compute the cross-group edge count and the modularity score. Plot both against the number of groups. There will be an "elbow" where adding more groups yields diminishing modularity improvement — that's the sweet spot.

#### Task 3: Core Extraction

Formalise the core group. Starting from the core library candidates identified in notebook 05 (Task 3):

**Step 1:** Begin with all libraries that appear in >80% of executable closures.

**Step 2:** Add libraries that are required by the core set (transitive dependencies of core libraries). This ensures the core group is self-contained — enabling core doesn't require enabling any feature group.

**Step 3:** Iteratively add libraries that have high cross-group dependency counts — libraries depended on by targets in 3+ non-core feature groups. These are better placed in core than in any single feature group, because putting them in one group forces all other groups to depend on that group.

**Step 4:** Evaluate the resulting core size. If core is too large (>40% of total targets), raise the inclusion thresholds. If too small (<10%), lower them. Report the core size and its compile time share.

#### Task 4: Contributor Alignment

Overlay contributor group ownership (from notebook 02) onto the proposed feature groups.

**Step 1:** For each feature group, compute the dominant owning team: which contributor group owns the most targets in this feature group?

**Step 2:** Compute the Normalised Mutual Information (NMI) between the feature group partition and the contributor group ownership partition. NMI = 1 means perfect alignment (each feature group is owned by exactly one team); NMI = 0 means no alignment.

**Step 3:** Also compute the Adjusted Rand Index (ARI) as a second measure of partition agreement.

**Step 4:** Identify misaligned targets: targets in a feature group where the owning team is NOT the group's dominant team. These are candidates for either moving to the feature group where their team's code lives, or transferring ownership to the dominant team.

**Step 5:** If alignment is poor, try re-running the feature group discovery with a modified cost function that penalises cross-team feature groups. Add a term to the community detection: edges between targets owned by the same team get a bonus weight, edges between targets owned by different teams get a penalty. This biases the algorithm toward feature groups that respect team boundaries.

#### Task 5: Feature Group Summary

For each proposed feature group (including core), report:
- Group name/ID.
- Number of library targets in the group.
- Number of executable targets that need this group.
- Total compile time of the group.
- Total SLOC of the group.
- Dominant owning team and ownership fraction.
- Number of incoming cross-group dependencies (other groups depend on this group).
- Number of outgoing cross-group dependencies (this group depends on other groups, excluding core).
- Self-containment score: `internal_edges / (internal_edges + outgoing_edges)`.

Save to `data/results/feature_groups.csv`.

Save the full target-to-group mapping to `data/processed/feature_group_assignments.parquet`:

| Column | Type | Description |
|---|---|---|
| `cmake_target` | str | Target name |
| `feature_group` | str | Assigned feature group |
| `target_type` | str | executable / library |

---

### 3.7 Notebook 07 — Feature Group Optimisation

**Purpose:** Identify structural changes (target splits, merges, interface extractions) that would improve feature group boundaries — reducing cross-group dependencies and minimising the number of feature groups each executable group requires.

#### Task 1: Cross-Group Dependency Analysis

For each cross-group dependency edge (a library in group A depending on a library in group B, where B ≠ core):
- Classify the dependency as thick (many headers used, deep integration) or thin (few headers used, minimal integration) using the thin dependency data from notebook 05.
- Classify by scope: PUBLIC (transitive), PRIVATE (non-transitive), or INTERFACE — from the edge list if available.
- Rank cross-group edges by impact: how many executables are forced to enable group B solely because of this one edge?

The highest-impact thin cross-group edges are the top candidates for structural change.

#### Task 2: Target Split Proposals

For high-impact cross-group dependency edges where the depended-on target is large (high file count, high compile time), propose a split:

**Step 1:** Build the file-level dependency graph within the target (from `-H` header inclusion data). Nodes are source files, edges are include relationships.

**Step 2:** Weight edges by co-change frequency (from git history — files that change together should stay together). Also weight by contributor group co-authorship (files maintained by the same team should stay together).

**Step 3:** Apply spectral partitioning (Fiedler vector of the graph Laplacian) or METIS partitioning to find the cut that minimises cross-partition dependencies while respecting constraints:
- All generated files from the same generator invocation stay together (indivisible).
- Files owned by the same contributor group should prefer to stay together (soft constraint — add edge weight for same-team ownership).

**Step 4:** Evaluate each proposed split:
- Number of cross-partition includes (these become new inter-target dependencies).
- Compile time balance between partitions.
- Which feature group each partition would belong to.
- Whether the split eliminates or reduces the cross-group dependency that motivated it.

Output proposed splits as a table.

#### Task 3: Interface Extraction Proposals

For thin cross-group dependencies that don't justify a full target split, propose interface extraction:
- Identify the specific headers and symbols used across the group boundary (from header inclusion data).
- Propose creating a lightweight interface target containing only those headers and their minimal dependencies.
- Place the interface target in the core group so that it doesn't create a new cross-group dependency.
- Estimate the compile time of the new interface target.

#### Task 4: Target Merge Proposals

Within each feature group, identify targets that could be merged:
- Targets with high mutual dependency (they already depend on each other — merging eliminates edges).
- Targets with the same owning team and similar profiles (from clustering analysis).
- Small targets (low file count, low compile time) that are consumed by exactly one other target in the same group — the overhead of a separate target exceeds the benefit.

For each proposed merge, evaluate:
- Net change in compile time (none, since the files are the same — but incremental rebuild scope increases).
- Net change in edge count (merging eliminates internal edges but inherits all external edges of both targets).
- Whether the merge changes the critical path.

#### Task 5: Executable Feature Mapping

After applying the proposed structural changes (in simulation), compute the revised feature group dependencies for each executable:
- For each executable, which feature groups does it need?
- Compare against the pre-optimisation feature group dependencies.
- Report the reduction: "executable X previously required 5 feature groups; after proposed changes, it requires 3."

Aggregate across executable groups (from notebook 05's executable clustering):
- For each executable group, what is the minimum set of feature groups needed?
- What is the total compile time of that minimum set?
- What is the reduction compared to building everything?

Save to `data/results/optimised_feature_mapping.csv`.

#### Task 6: Constrained Optimisation (Optional / Advanced)

If the heuristic split/merge/extract proposals from Tasks 2–4 leave significant cross-group coupling, run a global optimisation.

**Formulation:** Define a cost function:
```
cost = α × cross_group_edges + β × cross_group_compile_time + γ × team_boundary_violations
```

Where:
- `cross_group_edges`: total number of dependency edges crossing feature group boundaries (excluding core).
- `cross_group_compile_time`: total compile time of targets involved in cross-group dependencies.
- `team_boundary_violations`: number of targets in a feature group not owned by the group's dominant team.
- `α`, `β`, `γ` are weights (tune to prioritise modularity vs build time vs team alignment).

**Search method:** Simulated annealing. Start from the current feature group assignment. At each step, randomly move a target to a different feature group or swap two targets between groups. Accept moves that reduce cost, and probabilistically accept moves that increase cost (with decreasing probability as temperature cools).

**Constraints:** Enforce that the dependency graph within each feature group (plus core) is valid — no target can depend on a target in a different non-core group unless the executable explicitly enables both groups.

This is computationally feasible for hundreds of targets. Run for a configurable number of iterations (e.g. 100,000) and report the best solution found.

---

### 3.8 Notebook 08 — Impact Simulation

**Purpose:** Quantify the expected improvement from the proposed changes. This bridges Part 3 (modularity) into Part 4 (recommendations) by providing concrete numbers.

#### Task 1: Per-Team Build Time Simulation

For each contributor group (team), simulate their daily development experience under the proposed feature group structure.

**Method:** Replay the last N months of git history. For each commit by a team member:
1. Identify which feature groups the team needs enabled (the groups containing the targets they work on, plus core, plus any groups those targets depend on).
2. Compute the set of targets that are built when those feature groups are enabled.
3. Identify the directly modified targets.
4. Compute the incremental rebuild set: transitive dependants of modified targets, restricted to enabled targets only.
5. Simulate the parallel build time of the rebuild set (same Ninja scheduler simulation as notebook 04).

Compare against the current state (all targets enabled, full rebuild set).

Report per-team:
- Current mean incremental build time.
- Proposed mean incremental build time.
- Reduction (absolute and percentage).
- Current P90 incremental build time.
- Proposed P90 incremental build time.

#### Task 2: Full Build Time Under Feature Subsets

Compute the full build time for each feature group combination:
- Core only.
- Core + each individual feature group.
- Core + each pair of feature groups.
- All groups (baseline).

Use the parallel build simulator to compute wall-clock times. Present as a table and a bar chart. This shows developers what build time to expect when they enable just the groups they need.

#### Task 3: Sensitivity Analysis on K

Run the feature group discovery (notebook 06) with different values of K (number of feature groups) from 2 to 10. For each K, compute:
- Cross-group edge count.
- Average per-team incremental build time.
- Number of feature groups the median executable requires.
- Core size (number of targets).

Plot all four metrics against K. There will be diminishing returns — identify the K where the curves flatten. Report this as the recommended number of feature groups.

#### Task 4: Schema Change Impact

From the codegen supplement: compute schema pain scores. For each schema input file (`.proto`, `.xsd`, `.y`, `.l`, etc.):
- Compute change frequency from git history.
- Compute the total compile time of all generated outputs across all targets.
- Pain score = change frequency × total downstream compile time.

Under the proposed feature group structure, schema changes may now only require rebuilding enabled feature groups rather than everything. Recompute pain scores with the feature group restriction and report the reduction.

#### Task 5: Risk Analysis

Identify risks in the proposed structure:
- Feature groups with a single-person bus factor on critical targets.
- Feature groups where the core dependency is deep (many transitive dependencies on core — changes to core still trigger large rebuilds).
- Proposed target splits that are technically difficult (files with high internal coupling that resist clean partitioning).

Rate each risk as high/medium/low based on impact and likelihood. This informs the recommendations in notebook 09.

---

### 3.9 Notebook 09 — Recommendations

**Purpose:** Synthesise all findings into a prioritised, sequenced action plan. This is Part 4 of the story.

#### Task 1: Action Compilation

Compile all proposed actions from notebooks 04–08 into a single list:

- **Build performance actions:** targets for compilation optimisation (from bottleneck regression), include cleanup candidates (from preprocessed size analysis), precompiled header candidates (from header depth analysis), generator optimisation targets (from codegen analysis).
- **Structural changes:** target splits (from notebook 07 Task 2), target merges (from notebook 07 Task 4), interface extractions (from notebook 07 Task 3).
- **Dependency cleanup:** unused dependencies to remove, thin dependencies to refactor.
- **Ownership changes:** contested targets to assign, cross-team dependencies to renegotiate, bus factor risks to address.
- **Schema changes:** proto/XSD schemas to split, generator options to change.

#### Task 2: Impact Scoring

For each action, estimate:
- **Build time impact:** Expected seconds saved per day (from change impact simulation). Use the Monte Carlo simulation for structural changes; use the regression model counterfactuals for compilation optimisation.
- **Modularity impact:** Reduction in cross-group edges, or reduction in feature groups required by executables.
- **Effort estimate:** Rough heuristic based on action type and target size. Splitting a 200-file target is harder than removing an unused dependency. Use a scale: small (1–2 days), medium (3–5 days), large (1–2 weeks), extra-large (2+ weeks).
- **Risk:** From notebook 08 Task 5.

#### Task 3: Dependency Ordering

Some actions are prerequisites for others. Build a dependency graph of the actions themselves:
- A target split must happen before the resulting targets can be assigned to different feature groups.
- An interface extraction must happen before the thin dependency it resolves can be removed from the feature group's dependencies.
- A schema split should happen before generator optimisation on the resulting smaller schemas.

Compute a topological sort of the actions. Actions with no prerequisites can be started immediately.

#### Task 4: ROI Ranking

Within each topological level (actions with satisfied prerequisites), rank by ROI:
```
ROI = (build_time_impact + modularity_impact_normalised) / effort_estimate
```

Where `modularity_impact_normalised` converts cross-group edge reduction to an equivalent time saving (using the change impact simulation to estimate how much rebuild time each cross-group edge costs).

Present the top 10 actions overall, and the top 3 per contributor group (team). This gives both a global priority list and per-team action plans.

#### Task 5: Reporting

Generate the following outputs in `data/results/`:

**`recommendations.csv`** — Full action list with columns: action ID, action type (split/merge/extract/cleanup/schema/optimise), affected targets, owning team, build time impact (seconds/day), modularity impact (edge reduction), effort estimate, risk rating, prerequisites, ROI score.

**`team_reports/`** — One Markdown file per contributor group summarising:
- The team's current targets, compile time share, and critical path involvement.
- Cross-team dependencies the team imposes on others and that others impose on it.
- Prioritised actions for the team, with expected impact.
- Feature group(s) the team's executables will need.

**`executive_summary.md`** — A one-page summary covering:
- Current state metrics (from notebook 03 dashboard).
- Proposed feature group structure (count, team alignment, core size).
- Expected build time improvement (global and per-team).
- Top 5 highest-ROI actions.
- Estimated total effort and timeline.

---

## 4. New Shared Library Functions

### 4.1 New module: `src/build_optimiser/contributors.py`

- `build_contributor_target_matrix(commits_df: pd.DataFrame, min_contributor_commits: int, min_target_commits: int) -> pd.DataFrame` — Builds and filters the contributor-target matrix.
- `normalise_to_distributions(matrix: pd.DataFrame) -> pd.DataFrame` — Normalises each row to sum to 1.
- `cluster_contributors_hierarchical(matrix: pd.DataFrame, metric: str) -> dict` — Runs hierarchical clustering with Ward linkage and returns dendrogram data and cluster assignments at multiple cut levels.
- `cluster_contributors_nmf(matrix: pd.DataFrame, k_range: range) -> dict` — Runs NMF for each K and returns W, H matrices and evaluation scores.
- `compute_ownership(commits_df: pd.DataFrame, groups_df: pd.DataFrame, half_life_days: int) -> pd.DataFrame` — Computes time-decayed ownership scores per target per group.
- `compute_bus_factor(commits_df: pd.DataFrame, groups_df: pd.DataFrame, recent_months: int) -> pd.DataFrame` — Computes active contributor count per target per group.

### 4.2 New module: `src/build_optimiser/features.py`

- `compute_exe_library_matrix(G: nx.DiGraph, target_types: pd.DataFrame) -> pd.DataFrame` — Computes the executable-library dependency matrix from the graph.
- `identify_core_libraries(exe_lib_matrix: pd.DataFrame, threshold: float) -> list[str]` — Identifies core libraries by appearance frequency.
- `expand_core(G: nx.DiGraph, core: list[str], max_fraction: float) -> list[str]` — Expands core to include transitive dependencies and high-cross-group targets, respecting a maximum core size.
- `compute_jaccard_matrix(exe_lib_matrix: pd.DataFrame) -> pd.DataFrame` — Pairwise Jaccard similarity between executables.
- `detect_thin_dependencies(G: nx.DiGraph, header_data: pd.DataFrame) -> pd.DataFrame` — Identifies thin dependencies using header inclusion data.

### 4.3 New module: `src/build_optimiser/partitioning.py`

- `bicluster_exe_library(matrix: pd.DataFrame, k_range: range) -> dict` — Runs spectral co-clustering for each K and returns bicluster assignments and evaluation metrics.
- `hierarchical_communities(G: nx.DiGraph, resolution_range: list[float]) -> dict` — Runs Leiden at multiple resolutions and builds a community dendrogram.
- `extract_feature_groups(communities: dict, core: list[str], ownership: pd.DataFrame) -> pd.DataFrame` — Assigns targets to feature groups considering community structure, core membership, and team alignment.
- `simulated_annealing_partition(G: nx.DiGraph, initial_assignment: pd.DataFrame, cost_weights: dict, iterations: int) -> pd.DataFrame` — Runs simulated annealing to optimise the feature group assignment.

### 4.4 Changes to `src/build_optimiser/simulation.py`

Add the following functions:

- `simulate_incremental_build(G: nx.DiGraph, modified_targets: list[str], target_times: dict, n_cores: int, enabled_targets: set[str] | None) -> float` — Simulates a parallel incremental build and returns wall-clock time. If `enabled_targets` is provided, restricts the rebuild set to only enabled targets (for feature group simulation).
- `replay_git_history(G: nx.DiGraph, commits: pd.DataFrame, target_times: dict, n_cores: int, enabled_targets_per_team: dict | None) -> pd.DataFrame` — Replays historical commits and returns per-commit incremental build times.
- `feature_subset_build_time(G: nx.DiGraph, feature_groups: pd.DataFrame, group_combination: list[str], target_times: dict, n_cores: int) -> float` — Computes full build time for a given combination of enabled feature groups.
- `sensitivity_analysis(G: nx.DiGraph, exe_lib_matrix: pd.DataFrame, target_times: dict, k_range: range, n_cores: int) -> pd.DataFrame` — Runs feature group discovery for each K and returns metrics (cross-group edges, build time, etc.) per K.

---

## 5. Additional Python Dependencies

Add to `pyproject.toml`:

```toml
# Additional dependencies for contributor analysis and feature group discovery
"scipy>=1.11"          # Jensen-Shannon divergence, hierarchical clustering, dendrogram
"adjustText>=1.1"      # Non-overlapping annotations on scatter plots
```

`scipy` may already be installed as a transitive dependency of scikit-learn, but it should be listed explicitly since it's used directly for hierarchical clustering and distance computations.

All other required functionality (NMF, spectral co-clustering, DBSCAN, PCA, StandardScaler) is provided by scikit-learn, which is already in the dependency list.

---

## 6. Implementation Order

1. Update `scripts/collect/06_git_history.py` (renumbered) to collect per-contributor-per-file commit data (section 1.1).
2. Add contributor consolidation: produce `contributor_target_commits.parquet` and `contributors.csv` (section 1.4).
3. Update `scripts/consolidate/build_target_metrics.py` to add `target_type` column (section 1.2).
4. Implement `src/build_optimiser/contributors.py` (section 4.1).
5. Implement `src/build_optimiser/features.py` (section 4.2).
6. Implement `src/build_optimiser/partitioning.py` (section 4.3).
7. Update `src/build_optimiser/simulation.py` with new functions (section 4.4).
8. Replace the existing notebooks with the revised set (notebooks 01–09).
9. Update `pyproject.toml` with additional dependencies.

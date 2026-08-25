# Paper Reference Implementation

The private `job-parsing-code` repository preserves the implementation used for the earlier hiring-audit paper. It is useful for understanding historical prompts, scripts, data flow, and operational decisions, but it is not part of LLM AuditKit and does not define the new package architecture.

The reference is a sanitized snapshot with a new Git history. Private datasets, complete generated results, images, notebooks with embedded outputs, logs, credentials, and machine-specific deployment artifacts were intentionally excluded. Two small, reviewed CSV samples are retained only to document the raw and regression-ready data shapes. The original research repository should be treated as an archive rather than an agent dependency.

## Sync the Reference

Repository access is private and requires an authorized GitHub account with SSH access configured. From the LLM AuditKit repository root, run:

```bash
python scripts/sync_reference_repo.py
```

The script reads [`references/job_parsing-code.json`](../references/job_parsing-code.json), clones the repository into the ignored `.references/` directory, fetches the pinned commit, and checks it out in detached-HEAD mode. Re-running the command updates the checkout to the manifest revision. It refuses to overwrite a dirty checkout or use a checkout whose `origin` differs from the manifest.

The current reference is:

- Repository: [`KirillUtyashev/job-parsing-code`](https://github.com/KirillUtyashev/job-parsing-code)
- Revision: `c9391854ea55806ec252625cd2f48fb9edb156cd`
- Local path: `.references/job_parsing-code/`

## How to Use It

Use the reference to answer questions such as how the paper scripts assembled prompts, transformed job data, launched model calls, or organized analysis. Then translate the underlying requirement into the contracts documented under `docs/`.

The paper's historical output-cleaning, regression, and plotting workflow is in `analysis/paper_results_analysis.R` within the reference checkout.

Use `samples/edsl_raw_results_sample.csv` to inspect the post-EDSL result shape and `samples/regression_ready_results_sample.csv` to inspect the cleaned regression input, including raw picks and log-probability-based pick columns. These slices are schema examples, not statistically representative data.

Do not treat legacy module boundaries, hard-coded paths, dependencies, or operational shortcuts as current design decisions. In particular:

- LLM AuditKit architecture documentation is authoritative when it conflicts with the reference.
- Do not copy credentials, private data, generated outputs, or machine-specific configuration.
- Keep Expected Parrot EDSL details behind the shared inference adapter described in [`components/inference.md`](components/inference.md).
- Preserve configurable template cardinality, stable identifiers, stage-specific checkpointing, and the documented CSV/YAML boundary.
- Cite the pinned revision and relevant reference path in an issue or pull request when the reference materially informs a decision.

## Updating the Snapshot

Updating the reference is a deliberate maintenance operation. Review the proposed code-only snapshot for data, generated artifacts, and secrets; commit and push it to the private reference repository; then update the manifest revision and this page in the same LLM AuditKit pull request.

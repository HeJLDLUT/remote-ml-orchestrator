# Validation, provenance, and handoff

Read this reference before declaring a remote experiment batch complete.

## Runtime acceptance

For every atomic run, require:

- exit code 0 and a completed status marker;
- all expected artifacts present and nonempty;
- no failed folds/trials/candidates hidden by an aggregate summary;
- code archive, input data, configuration, and dependency hashes recorded;
- executing host, timestamps, allocated resources, and exact command recorded;
- stdout/stderr retained even when the run succeeds.

Retry from an existing checkpoint only after confirming the checkpoint matches the same scientific configuration and is not partially written. A retry replaces the failed ownership entry; it does not create a second competing result directory.

## Scientific acceptance

Adapt the checks to the project, but prediction workflows should normally verify:

- declared train/validation/test populations and counts;
- zero forbidden group/entity overlap between partitions;
- the held-out population was absent from feature, model, and hyperparameter selection;
- every required seed and fold has row-level predictions;
- unique record identifiers map to the intended source rows;
- metrics are independently recomputed from row-level targets and predictions;
- aggregate mean and sample standard deviation reproduce the published summary;
- transformations and inverse transformations reproduce saved values;
- stochastic differences stay within the declared reproducibility contract.

When comparing models, first test whether validation records are identical per seed. Equal sample counts are not evidence of identical populations. Report comparisons as paired only when identifiers and targets match record-for-record; otherwise describe them as comparisons across separate holdouts.

## Transfer integrity

Create a recursive SHA-256 manifest after the remote result directory stops changing. Copy each run into a unique local destination, verify the manifest, then merge or summarize. Preserve raw predictions, configuration, logs, and manifests; derived tables are not substitutes for raw outputs.

`verify_bundle.py create` writes a manifest outside the result root by default. `verify` reports missing, changed, and unexpected files and exits nonzero on any mismatch unless `--allow-extra` is supplied.

## Final audit package

Keep a compact machine-readable audit bundle containing:

- run matrix with final status and node assignment;
- pre-launch and representative runtime resource snapshots;
- environment and hardware versions;
- code/data/result manifests;
- per-run commands, logs, status, and selected parameters;
- validation report with recomputed metrics and leakage checks;
- transfer and temporary-access cleanup results.

The user-facing handoff should lead with the result, identify failed or excluded runs, summarize the scientific validation, state any comparability limits, and link exact local artifact paths. Do not edit a manuscript, upload results elsewhere, or remove durable remote environments unless the user requested those actions.

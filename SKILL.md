---
name: remote-ml-orchestrator
description: Orchestrate authorized machine-learning experiment batches across SSH-accessible Linux CPU or GPU nodes. Use when a task needs remote resource discovery, reproducible environment provisioning, load-aware scheduling, resilient execution, monitoring, result repatriation, and verification; do not use for managed cluster schedulers or cloud-account provisioning unless the user asks.
---

# Remote ML Orchestrator

Run each experiment exactly once, preserve its scientific design, use idle remote capacity aggressively but safely, and return locally verified results with a reproducible audit trail.

## Establish the run contract

Before touching a server, inspect the project and write a run matrix with one row per atomic experiment. For every row record the dataset/configuration, command, seeds, expected outputs, checkpoint behavior, CPU/GPU and memory needs, and an initial cost class. Treat data definitions, splits, feature selection, model search spaces, tuning budgets, seeds, and metrics as immutable unless the user explicitly authorizes a scientific redesign.

Identify the project's real entry point and dependency source of truth. Prefer an existing lockfile, environment file, container, or tested environment export over inferring versions from imports. Confirm that concurrent runs write to disjoint directories.

## Resolve access and topology

Use the user's existing SSH configuration and aliases first. Verify access with a non-mutating command. If a temporary key or bastion setup is actually required, read [references/ssh-and-environments.md](references/ssh-and-environments.md) before proceeding. Adding or removing an authorized key is a remote mutation: explain the exact scope, use a task-specific key, and remove only its exact public-key line after local acceptance.

## Audit resources

Probe every candidate node immediately before scheduling. Collect logical cores, 1/5/15-minute load, available memory, home-filesystem capacity/type, top CPU consumers, Python availability, and GPU free memory/utilization when present. Use:

```bash
python scripts/probe_nodes.py --hosts hosts.json --output inventory.json
```

The host file schema and shared-filesystem checks are in [references/ssh-and-environments.md](references/ssh-and-environments.md). Exclude unreachable, memory-constrained, disk-constrained, or heavily loaded nodes; an excluded node remains eligible for a later re-probe.

## Budget and schedule

Reserve by default at least the larger of 25% of logical CPUs or 8 logical CPUs, plus 16 GiB of available memory, on every node. Tighten these reserves when existing work is latency-sensitive or memory-heavy. Never consume capacity merely because it is visible.

Choose one level of parallelism. Keep the product of concurrent experiments, outer workers, inner estimator threads, BLAS threads, and data-loader workers within the node budget. Prefer independent experiments or outer CV folds with one estimator thread over nested parallelism unless a benchmark proves otherwise.

Create the initial allocation with:

```bash
python scripts/plan_runs.py --inventory inventory.json --tasks tasks.json --output run-plan.json
```

Read [references/scheduling-and-runtime.md](references/scheduling-and-runtime.md) when choosing task sizes, GPU placement, launch commands, or dynamic queue behavior. Keep `run-plan.json` as the single source of truth for task-to-node ownership; never launch the same atomic experiment on two nodes unless explicitly recovering a failed run after checking its checkpoint and ownership.

## Provision reproducibly

Create a namespaced remote root containing package, environment, logs, control files, and artifacts. Test whether home storage is shared before building duplicate environments. Transfer an immutable package archive, compare its SHA-256 locally and remotely, then create an environment whose name or manifest is tied to the dependency-lock hash. Verify imports and record exact versions before formal runs. Use a local wheelhouse only when remote network access is unavailable.

## Benchmark and estimate

Before the formal batch, run the smallest representative pilot that exercises the expensive path, such as one fold or one short trial. Benchmark at least two safe parallelism settings when nested libraries may oversubscribe. Confirm numerically identical outputs where determinism is expected. Use the observed time and the run matrix to give the user a range estimate, assumptions, and the dominant uncertainty before launching the full workload.

## Launch and monitor

Launch each task with low scheduling priority, explicit thread limits, an independent log, PID/control files, and checkpoint-aware restart behavior. Detach it so an SSH disconnect does not terminate the run. Capture the node, command, code/data hashes, environment versions, thread/GPU allocation, start time, and initial resource snapshot in a machine-readable run manifest.

Re-probe periodically and whenever a task ends. Dispatch queued work to the first node with sufficient safe capacity. If available memory crosses the reserve or pre-existing workloads become constrained, pause or throttle only this workflow's verified process groups; resume after headroom recovers. Never signal, renice, or terminate unrelated processes.

## Collect and verify

After each task completes, verify expected files and scientific invariants before freeing its run-matrix row. Create a result manifest on the remote side, transfer into a non-conflicting local directory, and verify every hash locally:

```bash
python scripts/verify_bundle.py create --root remote-results-copy --manifest result-manifest.json
python scripts/verify_bundle.py verify --root local-results --manifest result-manifest.json
```

Read [references/validation-and-handoff.md](references/validation-and-handoff.md) for prediction-level validation, split-leakage checks, metric recomputation, provenance, cleanup, and the final report.

## Completion gate

Finish only when every run-matrix row is `verified` or has a clearly reported blocker; all artifacts have matching hashes locally; required metrics have been independently recomputed from predictions; run manifests identify the executing node and environment; no temporary access remains; and the user has a concise result summary plus exact local artifact paths.

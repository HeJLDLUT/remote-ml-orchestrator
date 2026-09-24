# Load-aware scheduling and resilient runtime

Read this reference when converting the resource inventory into thread/GPU assignments, launching jobs, or adapting to live load.

## Atomic runs and budgets

An atomic run owns one output directory and can be restarted independently. Split a batch by dataset, strategy, seed, model family, or another natural checkpoint boundary only when doing so preserves the intended selection and validation protocol.

For a node with `C` logical CPUs and five-minute load `L`, begin with:

```text
reserved_cpu = max(8, ceil(0.25 * C))
allocatable_new_threads = max(0, floor(C - reserved_cpu - L))
allocatable_memory_gb = max(0, available_memory_gb - 16)
```

Treat this as an upper bound, not a target. Reduce it when the process list shows interactive, database, compilation, or memory-intensive work. Estimate memory per worker from a pilot and constrain workers by both CPU and memory.

For outer parallelism `O` and estimator/BLAS threads `I`, enforce `O × I <= allocatable_new_threads`, including concurrent experiments. Set `OMP_NUM_THREADS`, `MKL_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `NUMEXPR_NUM_THREADS`, framework data-loader workers, and estimator `n_jobs` explicitly. Outer folds or independent trials with `I=1` are usually safer than nested parallelism.

## Task planning schema

`plan_runs.py` accepts a JSON list or an object with a `tasks` list:

```json
{
  "tasks": [
    {
      "id": "dataset-a_seed-42",
      "command": ["python", "train.py", "--config", "a.json", "--seed", "42"],
      "threads": 12,
      "memory_gb": 24,
      "gpus": 0,
      "gpu_memory_gb_each": 0,
      "estimated_minutes": 180,
      "priority": 10,
      "required_tags": ["cpu"],
      "allowed_nodes": ["cpu-a", "cpu-b"],
      "output_dir": "artifacts/dataset-a_seed-42"
    }
  ]
}
```

`command` may be a string for reporting or an argument array for safer execution. `threads` and `memory_gb` are required positive budgets. GPU tasks receive concrete device indices in the generated plan; launch them with the returned `CUDA_VISIBLE_DEVICES`. Omit `allowed_nodes` and `required_tags` when unrestricted.

The planner performs an initial conservative allocation. It does not launch jobs or replace monitoring. Re-run the probe and planner, or allocate the next queued task manually from the same rules, after a task finishes or node conditions change.

## Pilot and ETA

Use a representative fold/trial to measure wall time and peak memory. If the workflow has phases, estimate them separately: preprocessing, screening, tuning, final CV, final fit, and artifact generation. Calculate a lower bound from total measured work divided by safe parallel capacity, then add checkpoint, transfer, and straggler overhead. Report a range rather than false precision and name the assumptions that dominate it.

## Resilient launch

Create one control directory per atomic run. Refuse to launch if its PID is alive or its completion marker already verifies. A typical Linux launch is:

```bash
run_id='dataset-a_seed-42'
run_dir="$HOME/ml-work/runs/$run_id"
mkdir -p "$run_dir/logs" "$run_dir/control" "$run_dir/artifacts"
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
nohup nice -n 10 ionice -c 2 -n 7 \
  python train.py --config a.json --output "$run_dir/artifacts" \
  >"$run_dir/logs/run.log" 2>&1 < /dev/null &
pid=$!
printf '%s\n' "$pid" >"$run_dir/control/pid"
```

Wrap the project command so it writes an atomic status file containing `running`, `completed` plus exit code 0, or `failed` plus the nonzero exit code and end time. Use a temporary file followed by `mv` so monitors never read a partial status. A PID alone is insufficient because Linux may reuse it; verify the PID's start time and command against the run manifest before signaling it.

## Dynamic queue

Keep unstarted tasks queued locally. When capacity appears:

1. refresh resource inventory;
2. mark completed/failed jobs from status and expected artifacts;
3. subtract live workflow allocations from each node's safe budget;
4. dispatch the highest-priority longest eligible task;
5. record ownership before launch;
6. repeat until no task fits.

Recheck at phase boundaries and every few minutes for long runs. If available memory falls below the reserve, pause the verified workflow process group with `SIGSTOP`; resume with `SIGCONT` only after headroom is stable. Prefer lowering future concurrency to repeated pause/resume cycles. On load pressure without memory pressure, let already-running low-priority work continue if the operating system is handling contention; reduce new dispatches first.

For GPU jobs, require enough free memory plus margin and avoid devices with sustained utilization from unrelated processes. Exclusive device assignment is the default. Sharing a GPU requires a measured memory envelope and explicit support from the framework.

#!/usr/bin/env python3
"""Create a conservative initial placement plan from node inventory and ML tasks."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def read_items(path: Path, key: str) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get(key, []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("%s must contain a JSON list or a '%s' list" % (path, key))
    return items


def validate_tasks(tasks: List[Dict[str, Any]]) -> None:
    seen = set()
    for task in tasks:
        task_id = task.get("id")
        if not task_id or task_id in seen:
            raise ValueError("Every task needs a unique non-empty 'id'")
        seen.add(task_id)
        if float(task.get("threads", 0)) <= 0 or float(task.get("memory_gb", 0)) <= 0:
            raise ValueError("Task %s needs positive threads and memory_gb" % task_id)
        if "command" not in task:
            raise ValueError("Task %s needs a command" % task_id)


def eligible(task: Dict[str, Any], node: Dict[str, Any], state: Dict[str, Any]) -> bool:
    if state["threads"] < int(task["threads"]) or state["memory_gb"] < float(task["memory_gb"]):
        return False
    allowed = task.get("allowed_nodes")
    if allowed and node["name"] not in allowed:
        return False
    required = set(task.get("required_tags", []))
    if not required.issubset(set(node.get("tags", []))):
        return False
    needed_gpus = int(task.get("gpus", 0))
    if needed_gpus:
        min_mem = float(task.get("gpu_memory_gb_each", 0)) * 1024.0
        candidates = [gpu for gpu in state["gpus"] if gpu["memory_free_mb"] >= min_mem]
        if len(candidates) < needed_gpus:
            return False
    return True


def take_gpus(task: Dict[str, Any], state: Dict[str, Any]) -> List[int]:
    count = int(task.get("gpus", 0))
    if not count:
        return []
    min_mem = float(task.get("gpu_memory_gb_each", 0)) * 1024.0
    candidates = sorted(
        [gpu for gpu in state["gpus"] if gpu["memory_free_mb"] >= min_mem],
        key=lambda gpu: (-gpu["memory_free_mb"], gpu["utilization_percent"], gpu["index"]),
    )
    chosen = candidates[:count]
    chosen_ids = {gpu["index"] for gpu in chosen}
    state["gpus"] = [gpu for gpu in state["gpus"] if gpu["index"] not in chosen_ids]
    return sorted(chosen_ids)


def task_sort_key(task: Dict[str, Any]) -> Tuple[float, float, float, float]:
    return (
        float(task.get("priority", 0)),
        float(task.get("estimated_minutes", 0)),
        float(task.get("threads", 0)),
        float(task.get("memory_gb", 0)),
    )


def choose_node(task: Dict[str, Any], nodes: List[Dict[str, Any]], states: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    candidates = []
    for node in nodes:
        state = states[node["name"]]
        if not eligible(task, node, state):
            continue
        cpu_ratio = state["threads"] / max(1.0, state["initial_threads"])
        mem_ratio = state["memory_gb"] / max(0.001, state["initial_memory_gb"])
        normalized_work = state["assigned_work"] / max(1.0, state["initial_threads"])
        score = (normalized_work, -min(cpu_ratio, mem_ratio), -state["threads"], node["name"])
        candidates.append((score, node))
    return min(candidates, key=lambda item: item[0])[1] if candidates else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--tasks", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    nodes = [node for node in read_items(args.inventory, "nodes") if node.get("status") == "ok"]
    tasks = read_items(args.tasks, "tasks")
    validate_tasks(tasks)
    states: Dict[str, Dict[str, Any]] = {}
    for node in nodes:
        threads = int(node.get("safe_new_threads", 0))
        memory = float(node.get("safe_new_memory_gb", 0))
        states[node["name"]] = {
            "threads": threads, "memory_gb": memory,
            "initial_threads": threads, "initial_memory_gb": memory,
            "gpus": list(node.get("gpus", [])), "assigned_work": 0.0,
        }

    assignments = []
    unassigned = []
    for task in sorted(tasks, key=task_sort_key, reverse=True):
        node = choose_node(task, nodes, states)
        if node is None:
            unassigned.append({"task_id": task["id"], "reason": "no node currently fits the declared budget"})
            continue
        state = states[node["name"]]
        gpu_ids = take_gpus(task, state)
        state["threads"] -= int(task["threads"])
        state["memory_gb"] -= float(task["memory_gb"])
        work = float(task.get("estimated_minutes", 1)) * int(task["threads"])
        state["assigned_work"] += work
        assignments.append({
            "task_id": task["id"], "node": node["name"], "target": node.get("target"),
            "threads": int(task["threads"]), "memory_gb": float(task["memory_gb"]),
            "gpu_indices": gpu_ids,
            "environment": {"CUDA_VISIBLE_DEVICES": ",".join(map(str, gpu_ids))} if gpu_ids else {},
            "command": task["command"], "output_dir": task.get("output_dir"),
            "estimated_minutes": task.get("estimated_minutes"),
        })

    remaining = {
        name: {"threads": state["threads"], "memory_gb": round(state["memory_gb"], 3),
               "gpu_indices": sorted(gpu["index"] for gpu in state["gpus"])}
        for name, state in states.items()
    }
    payload = {"schema_version": 1, "assignments": assignments,
               "unassigned": unassigned, "remaining_capacity": remaining}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Planned %d tasks; %d unassigned; wrote %s" % (len(assignments), len(unassigned), args.output))
    return 0 if not unassigned else 3


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Probe SSH-accessible Linux nodes and calculate conservative free capacity."""

import argparse
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List


REMOTE_PROBE = r'''LC_ALL=C bash -lc '
set -u
cores=$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc)
read load1 load5 load15 rest < /proc/loadavg
mem_kb=$(awk "/^MemAvailable:/ {print \$2}" /proc/meminfo)
disk_kb=$(df -Pk "$HOME" | awk "NR==2 {print \$4}")
fs_type=$(df -PT "$HOME" | awk "NR==2 {print \$2}")
printf "hostname=%s\n" "$(hostname -f 2>/dev/null || hostname)"
printf "logical_cores=%s\nload_1m=%s\nload_5m=%s\nload_15m=%s\n" "$cores" "$load1" "$load5" "$load15"
printf "memory_available_kb=%s\ndisk_available_kb=%s\nhome_fs_type=%s\n" "$mem_kb" "$disk_kb" "$fs_type"
printf "kernel=%s\n" "$(uname -srmo 2>/dev/null || uname -a)"
if command -v python3 >/dev/null 2>&1; then printf "python3=%s\n" "$(python3 --version 2>&1)"; fi
ps -eo user=,pid=,pcpu=,pmem=,comm= --sort=-pcpu 2>/dev/null | head -n 8 | awk "{printf \"process=%s|%s|%s|%s|%s\\n\", \$1,\$2,\$3,\$4,\$5}"
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=index,name,memory.total,memory.free,utilization.gpu --format=csv,noheader,nounits 2>/dev/null | sed "s/, /|/g; s/^/gpu=/"
fi
' '''


def load_hosts(path: Path) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    hosts = data.get("hosts", []) if isinstance(data, dict) else data
    if not isinstance(hosts, list) or not hosts:
        raise ValueError("Host file must contain a non-empty JSON list or a 'hosts' list")
    seen = set()
    normalized = []
    for item in hosts:
        if not isinstance(item, dict) or not item.get("name") or not item.get("target"):
            raise ValueError("Every host requires string fields 'name' and 'target'")
        if item["name"] in seen:
            raise ValueError("Duplicate host name: %s" % item["name"])
        seen.add(item["name"])
        normalized.append(item)
    return normalized


def ssh_command(host: Dict[str, Any], timeout: int) -> List[str]:
    cmd = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=%d" % timeout,
        "-o", "ServerAliveInterval=15",
        "-o", "ServerAliveCountMax=2",
    ]
    if host.get("port"):
        cmd += ["-p", str(host["port"])]
    if host.get("jump"):
        cmd += ["-J", str(host["jump"])]
    if host.get("identity_file"):
        cmd += ["-i", os.path.expandvars(os.path.expanduser(str(host["identity_file"])))]
    cmd += [str(host["target"]), REMOTE_PROBE]
    return cmd


def parse_probe(stdout: str) -> Dict[str, Any]:
    values: Dict[str, Any] = {"processes": [], "gpus": []}
    for raw in stdout.splitlines():
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        if key == "process":
            fields = value.split("|", 4)
            if len(fields) == 5:
                values["processes"].append({
                    "user": fields[0], "pid": int(fields[1]),
                    "cpu_percent": float(fields[2]), "memory_percent": float(fields[3]),
                    "command": fields[4],
                })
        elif key == "gpu":
            fields = value.split("|", 4)
            if len(fields) == 5:
                values["gpus"].append({
                    "index": int(fields[0]), "name": fields[1],
                    "memory_total_mb": float(fields[2]), "memory_free_mb": float(fields[3]),
                    "utilization_percent": float(fields[4]),
                })
        else:
            values[key] = value
    required = ["logical_cores", "load_5m", "memory_available_kb", "disk_available_kb"]
    missing = [key for key in required if key not in values]
    if missing:
        raise ValueError("Probe output missing: %s" % ", ".join(missing))
    for key in ("logical_cores", "memory_available_kb", "disk_available_kb"):
        values[key] = int(float(values[key]))
    for key in ("load_1m", "load_5m", "load_15m"):
        values[key] = float(values[key])
    return values


def capacity(host: Dict[str, Any], values: Dict[str, Any]) -> Dict[str, Any]:
    cores = int(values["logical_cores"])
    fraction = float(host.get("reserve_fraction", 0.25))
    reserve_cores = int(host.get("reserve_cores", 8))
    reserved = max(reserve_cores, int(math.ceil(cores * fraction)))
    safe_threads = max(0, int(math.floor(cores - reserved - float(values["load_5m"]))))
    mem_gb = values["memory_available_kb"] / 1024.0 / 1024.0
    disk_gb = values["disk_available_kb"] / 1024.0 / 1024.0
    reserve_mem = float(host.get("reserve_memory_gb", 16.0))
    return {
        "reserved_cores": reserved,
        "safe_new_threads": safe_threads,
        "memory_available_gb": round(mem_gb, 3),
        "safe_new_memory_gb": round(max(0.0, mem_gb - reserve_mem), 3),
        "home_disk_available_gb": round(disk_gb, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hosts", required=True, type=Path, help="JSON host inventory")
    parser.add_argument("--output", required=True, type=Path, help="Output JSON inventory")
    parser.add_argument("--connect-timeout", type=int, default=8)
    parser.add_argument("--command-timeout", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true", help="Print SSH commands without connecting")
    args = parser.parse_args()

    hosts = load_hosts(args.hosts)
    nodes = []
    for host in hosts:
        command = ssh_command(host, args.connect_timeout)
        base = {"name": host["name"], "target": host["target"], "tags": host.get("tags", [])}
        if args.dry_run:
            base.update({"status": "dry-run", "ssh_argv": command})
            nodes.append(base)
            continue
        try:
            result = subprocess.run(command, capture_output=True, text=True,
                                    timeout=args.command_timeout, check=False)
            if result.returncode != 0:
                base.update({"status": "unreachable", "error": result.stderr.strip(),
                             "returncode": result.returncode})
            else:
                values = parse_probe(result.stdout)
                base.update({"status": "ok", **values, **capacity(host, values)})
        except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
            base.update({"status": "error", "error": str(exc)})
        nodes.append(base)

    payload = {"schema_version": 1, "nodes": nodes}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    ok = sum(node["status"] == "ok" for node in nodes)
    print("Probed %d nodes: %d available; wrote %s" % (len(nodes), ok, args.output))
    return 0 if ok or args.dry_run else 2


if __name__ == "__main__":
    sys.exit(main())

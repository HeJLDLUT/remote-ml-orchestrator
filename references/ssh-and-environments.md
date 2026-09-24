# SSH access and reproducible environments

Read this reference when access uses multiple aliases, jump hosts, temporary keys, shared storage, offline nodes, or per-node environments.

## Host inventory

`probe_nodes.py` accepts a JSON list or an object with a `hosts` list:

```json
{
  "hosts": [
    {
      "name": "cpu-a",
      "target": "user@cpu-a.example.org",
      "port": 22,
      "jump": "user@gateway.example.org",
      "identity_file": "C:/secure/task_key",
      "tags": ["cpu", "large-memory"],
      "reserve_fraction": 0.25,
      "reserve_cores": 8,
      "reserve_memory_gb": 16
    }
  ]
}
```

Only `name` and `target` are required. Prefer SSH aliases from the user's SSH config; omit `jump`, `port`, and `identity_file` when the alias already defines them. Paths are expanded locally. The probe never writes remotely.

## Access sequence

Test `ssh -o BatchMode=yes -o ConnectTimeout=8 <target> true`. Preserve host-key checking. Add a host key to a task-specific `known_hosts` file only after the user can authenticate the host identity or the existing trusted configuration supplies it.

When an existing interactive client holds credentials that OpenSSH cannot use, first look for an authorized non-secret connection route such as an SSH alias, agent forwarding already configured by the user, or a gateway. A temporary task key is the last resort. Generate a new Ed25519 key with a unique comment; never reuse a personal Git, repository, or unrelated service key.

To add a public key idempotently, show the user the exact public line and use a command shaped like this on each authorized endpoint:

```bash
pub='ssh-ed25519 AAAA... unique-task-comment'
umask 077
mkdir -p "$HOME/.ssh"
touch "$HOME/.ssh/authorized_keys"
grep -qxF "$pub" "$HOME/.ssh/authorized_keys" || printf '%s\n' "$pub" >> "$HOME/.ssh/authorized_keys"
```

Record every endpoint on which the line was added. Cleanup must remove that exact full line, preserve all other entries, and verify that authentication with the temporary key is rejected. Delete the local private key only after locally transferred results pass validation.

## Shared storage test

Do not infer shared home storage from similar paths. Create a harmless random marker below the task root on one node, then test for that exact marker from the other nodes. Remove the marker after the test. Shared package, environment, and results directories need one writer for environment creation and unique subdirectories for concurrent runs.

Use local scratch for high-I/O temporary data when available, but keep checkpoints and final artifacts on durable storage. Record scratch-to-durable synchronization in the run manifest.

## Package transfer

Build one immutable archive from the exact local run package. Exclude caches, previous results, secrets, large unrelated artifacts, and local virtual environments. Hash the archive locally, transfer it, hash it remotely, and extract only after the hashes match. Keep the archive or its manifest so every node runs identical code and inputs.

## Environment selection

Use the project's declared Python version. If only a range is declared, choose a version supported by all compiled dependencies and record the choice. Prefer, in order:

1. an existing project container or lockfile-backed environment;
2. a virtual environment or Conda environment built from an exact lock/export;
3. a captured set of tested versions when the project has no lock.

Tie the environment directory to a hash of the dependency specification, for example `envs/py311-<lockhash>`. Verify both imports and versions for the libraries actually used by the project. For GPU workloads also record the driver, CUDA runtime, framework CUDA build, and visible device.

If nodes have no external network, download a Linux wheelhouse once for the target Python/platform on an authorized networked machine, hash it, distribute it, and install with `--no-index --find-links`. Do not silently substitute package versions when a wheel is unavailable; report the incompatibility or build from an explicitly accepted source.

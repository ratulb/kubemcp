# kubemcp — AGENTS.md

**Compact reference for OpenCode agents. The full source of truth is [`README.md`](./README.md).**

## Entrypoints
- `k8s_mcp_server.py` — MCP server with 5 tools (write_config, read_config, create_cluster, destroy_cluster, get_cluster_status). Self-bootstraps `mcp` package via a 6-layer fallback chain: existing `.venv` → fresh `.venv` → `sudo apt install python3-venv` → `pip install --user` → `get-pip.py` bootstrap → detailed error with manual fix. Uses `sudo -n` for apt and `os.execv` to re-launch into the venv.
- `opencode.json` — registers it with OpenCode (local python3 + python path).
- `./cluster.sh` — interactive menu fallback. Must run as root/sudo.
- No package.json — pure bash scripts sourced via `. script.sh`.

## Key quirks
- `utils.sh` auto-calls `read_setup()` at line 23 — sourcing it immediately reads `setup.conf` and exports vars.
- Scripts use `. script.sh` sourcing, not `bash script.sh`. `_ret()` helper detects context: `return 1` when sourced, `exit 1` when direct. Use `_ret` in `launch-cluster.sh` error paths.
- `remote_script <host> <file>` — runs a local script on remote via SSH stdin. `remote_cmd <host> <args>` — runs one command. `remote_copy <src> <dst>` — SCP with `StrictHostKeyChecking=no`.
- **Remote redirects**: `remote_cmd $host "echo ... | sudo tee -a /etc/file"` — bare `>>` runs on controller.
- `quiet=yes` env var suppresses SSH output in validation functions (used internally by `can_access_address`, `validate_single_master_configuration`, etc.).
- **sed delimiter**: use `|` not `/` for `#pod_network_cidr#` (CIDR value contains `/`).
- `pod_network_cidr` is **not** reset by `reset_setup_configuration()` (fixed bug — zeroing it broke subsequent runs).
- Single-node: LB port must differ from 6443 (use 6643). LB + first master on same machine.

## Key commands
```bash
bash tests/e2e-single-node.sh [lb_type]
bash tests/e2e-multi-node.sh [iterations]
bash tests/test.sh [count]
debug=yes sudo ./cluster.sh
sudo bash cleanup-all.sh
```

## Gotchas
- `kube-remove.sh` does aggressive cleanup — safe to run repeatedly.
- `install-kubeadm.sh` installs containerd if missing (bare Ubuntu).
- `cleanup-all.sh` auto-cleans remote masters/workers via SSH. No manual remote cleanup needed.
- `debug` env var suppresses temp file cleanup and enables `debug()` print calls.
- `console.sh` drops into interactive bash from the menu (`exit` to return).
- Controller SSH key must be in `~/.ssh/authorized_keys` on every remote node; all nodes need passwordless sudo; same SSH username across all nodes.
- `install-cni-pluggin.sh` — note the typo (double `g`).
- `envoy/install-envoy.script` uses `.script` extension (not `.sh`). It is sourced, not executed directly.
- `tests/e2e-single-node.sh` runs `bash -c ". script.sh"` per step to isolate sourced scripts and prevent exit-code leaks.
- `install-docker.sh` is a no-op — Docker is not used.

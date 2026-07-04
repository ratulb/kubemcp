# kubemcp — AGENTS.md

## Entrypoints
- `k8s_mcp_server.py` — MCP server with 5 tools (write_config, read_config, create_cluster, destroy_cluster, get_cluster_status). Self-bootstraps: creates `.venv` + `pip install mcp` if `mcp` module is missing.
- `opencode.json` — registers it with OpenCode (local python3 + python path).
- `./cluster.sh` — interactive menu fallback. Must run as root/sudo.
- No package.json, no test framework — pure bash scripts sourced via `. script.sh`.

## Execution quirks
- `utils.sh` auto-calls `read_setup()` at line 23 — sourcing it immediately reads `setup.conf` and exports vars.
- Scripts use `. script.sh` sourcing, not `bash script.sh`. `_ret()` helper detects context: `return 1` when sourced, `exit 1` when direct. Use `_ret` in `launch-cluster.sh` error paths.
- `remote_script <host> <file>` — runs a local script on remote via SSH stdin. `remote_cmd <host> <args>` — runs one command. `remote_copy <src> <dst>` — SCP with `StrictHostKeyChecking=no`.
- **Remote redirects**: `remote_cmd $host "echo ... | sudo tee -a /etc/file"` — bare `>>` runs on controller.

## Templating
- `kubeadm-init.sh` is a template with placeholders `#masters#`, `#lb_port#`, `#loadbalancer#`, `#pod_network_cidr#`. Copied to `kubeadm-init.sh.tmp`, sed-replaced, then **sourced** as a script.
- **sed delimiter**: use `|` not `/` for `#pod_network_cidr#` (CIDR value contains `/`).

## Config
- `setup.conf` — key=value. Menu writes temp files under `/tmp/`, then `configure_multi_master_setup()` syncs them.
- `pod_network_cidr` is **not** reset by `reset_setup_configuration()` (fixed bug — zeroing it broke subsequent runs).
- Single-node: LB port must differ from 6443 (use 6643). LB + first master on same machine.

## Calico CNI
- `install-cni-pluggin.sh` patches the manifest: `CALICO_IPV4POOL_IPIP` → `"Never"`, `CALICO_IPV4POOL_VXLAN` → `"Always"`. IPIP is blocked by most clouds; VXLAN (UDP 4789) is used instead.
- Note the typo in the filename.

## sudo patterns
- `sudo tee -a` for appending to protected files (`sudo echo >>` doesn't work — redirect runs as user).
- `sudo -n` in the MCP server (non-interactive).

## Key commands
```bash
# Single-node test (envoy, nginx, or haproxy)
bash tests/e2e-single-node.sh [lb_type]

# Multi-node (requires setup.conf with workers)
bash tests/e2e-multi-node.sh [iterations]

# Stress test (default 20 iterations)
bash tests/test.sh [count]

# Debug mode — preserves temp files
debug=yes sudo ./cluster.sh

# Full nuclear teardown
sudo bash cleanup-all.sh
```

## Gotchas
- `kube-remove.sh` does aggressive cleanup (iptables flush, containerd reset, apt purge) — safe to run repeatedly.
- `install-kubeadm.sh` installs containerd if missing (bare Ubuntu).
- `debug` env var suppresses temp file cleanup and enables `debug()` print calls.
- `console.sh` drops into interactive bash from the menu (`exit` to return).
- Controller SSH key must be in `~/.ssh/authorized_keys` on every remote node; all nodes need passwordless sudo.
- `tests/e2e-single-node.sh` runs `bash -c ". script.sh"` per step to isolate sourced scripts and prevent exit-code leaks.

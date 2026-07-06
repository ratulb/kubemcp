# kubemcp

**Spin up a production-style Kubernetes cluster from one machine — via MCP (Model Context Protocol).**

Under the hood it wraps the [k8s-easy-install](https://github.com/ratulb/k8s-easy-install) project as an MCP server. The same installer scripts ship with this repo, so you can also use them directly from the CLI.

| Capability | Details |
|---|---|
| Nodes | Single-node or multi-node (control-plane + workers) |
| Load balancers | HAProxy, NGINX, or Envoy |
| CNI | Calico (VXLAN — works in all clouds) |
| K8s version | v1.36.2 (from pkgs.k8s.io) |
| Runtime | containerd |
| Controller | Any Linux machine with SSH access to nodes |
| Tested OS | Debian 11/12/13, Ubuntu 20.04/22.04/24.04 |

---

## Quick start — MCP

`opencode.json` in the project root registers the MCP server automatically. OpenCode loads these tools:

| Tool | Description |
|---|---|
| `write_config` | Write cluster config to `setup.conf` (validates inputs) |
| `read_config` | Read current `setup.conf` |
| `create_cluster` | Build the full cluster — config, LB, kubeadm init, CNI, join nodes |
| `destroy_cluster` | Full nuclear teardown — LB + k8s + repos + remote nodes |
| `get_cluster_status` | Node status + all pods |

**Self-bootstrapping**: The server auto-installs the `mcp` package using a multi-layer fallback chain so you never need to manually install dependencies:

```
 1. Install/upgrade inside an existing .venv
 2. Create a fresh .venv + pip install mcp
 3. sudo apt install python3-venv python3-pip, retry venv
 4. pip install --user mcp (with/without --break-system-packages)
 5. Bootstrap pip via get-pip.py, then install
 6. Print clear error with manual fix commands
```

The process is transparent — the server simply works.

### Example usage

```
write_config masters="localhost" workers="" loadbalancer="localhost" lb_type="haproxy" lb_port="6643" pod_network_cidr="192.168.0.0/16"
create_cluster
get_cluster_status
destroy_cluster
```

> **Single-node caveat**: LB port must differ from 6443 (use 6643). LB runs on the same machine as the first master.

---

## Quick start — CLI

```bash
git clone https://github.com/ratulb/kubemcp.git
cd kubemcp
sudo ./cluster.sh
```

Follow the interactive menu:

1. **Cluster setup** — LB address:port, LB type, master IPs, worker IPs
2. **Launch** — press `y` when prompted

In 2–3 minutes you have a running cluster with `kubectl` on the controller.

---

## Prerequisites

### Controller machine
- **`python3`, `python3-venv`, `python3-pip`** — the MCP server auto-bootstraps. If `python3-venv` is missing it runs `sudo apt install` automatically.
- **Passwordless sudo** — required for cluster operations and auto-installing system packages.

### Cluster nodes (remote)
- Controller SSH key in `~/.ssh/authorized_keys` on every remote node (LB, master, worker)
- Passwordless sudo for the SSH user on all nodes
- Same SSH username across all nodes (or use `~/.ssh/config` `User` directives)
- Network: all nodes reachable on ports **22**, **6443**, the chosen **LB port**; **UDP 4789** for Calico VXLAN

---

## Architecture

```
Controller ──SSH──► LB (haproxy/nginx/envoy)
                       │
           ┌───────────┼───────────┐
           ▼           ▼           ▼
       Master 1    Master 2..N    Worker
     (kubeadm init)  (join)      (join)
```

The controller is **not** joined to the cluster — `kubectl` is installed as a standalone binary with kubeconfig copied from the first master. The controller can be the same machine as the first master (`masters=localhost`) or a completely separate machine.

---

## Pipeline

`launch-cluster.sh` orchestrates every step in order:

```
 1. Validate SSH connectivity to every node (LB, masters, workers)
 2. Install & configure the chosen load balancer on the LB node
 3. For every master:
      kube-remove.sh       — nuke any existing k8s installation
      install-kubeadm.sh   — install kubelet/kubeadm/kubectl + containerd
 4. First master only:
      kubeadm-init.sh.tmp  — template rendered with real values
      prepare-cluster-join.sh  — extract join commands from log
      install-cni-pluggin.sh   — deploy Calico CNI (VXLAN mode)
 5. Remaining masters:  master-join-cluster.cmd
 6. Workers:            worker-join-cluster.cmd
 7. init-self.sh       — download kubectl, copy kubeconfig to controller
 8. test-commands.sh   — smoke test: deploy nginx, wait for pods
 9. clean-trash.sh     — remove temp files (unless $debug is set)
```

### Template engine

`kubeadm-init.sh` is a template with placeholders replaced at runtime:

| Placeholder | Replaced with |
|---|---|
| `#masters#` | Space-separated master hostnames |
| `#lb_port#` | Chosen LB port |
| `#loadbalancer#` | LB hostname/IP |
| `#pod_network_cidr#` | Pod CIDR from `setup.conf` |

`launch-cluster.sh` copies it to `kubeadm-init.sh.tmp` and runs `sed` substitutions before sourcing it. **Use `|` as sed delimiter for `#pod_network_cidr#`** because CIDR values contain `/`.

Join commands are extracted from the first master's `kubeadm-init.log` by `prepare-cluster-join.sh`:
- `master-join-cluster.cmd` — for additional control-plane nodes (has `--control-plane` flag)
- `worker-join-cluster.cmd` — for worker nodes

Both generated files are in `.gitignore`.

### Remote execution model

All remote operations use three helpers from `utils.sh`:

```bash
remote_script <host> <local-file>   # Run a local script on remote (SSH stdin)
remote_cmd    <host> <args...>      # Run a one-shot command on remote
remote_copy   <src> <dst>           # SCP with StrictHostKeyChecking=no
```

There is no agent, no daemon, no configuration management tool — everything uses plain SSH with strict host key checking disabled (ephemeral cloud nodes).

---

## Configuration

### setup.conf

Key=value file. Edit directly or use the menu/`write_config` tool.

| Key | Example | Purpose |
|---|---|---|
| `masters` | `m-1 m-2` | Space-separated master hostnames/IPs |
| `workers` | `w-1 w-2` | Space-separated worker hostnames/IPs (empty = single-node) |
| `loadbalancer` | `10.0.0.10` | LB hostname or IP |
| `lb_type` | `haproxy` | One of: `haproxy`, `nginx`, `envoy` |
| `lb_port` | `7443` | LB listen port (must not be 6443 on single-node) |
| `pod_network_cidr` | `192.168.0.0/16` | Pod CIDR passed to `kubeadm init --pod-network-cidr` |
| `sleep_time` | `3` | Seconds between status-check retries |
| `cri_containerd_cni_ver` | `1.3.4` | Informational — not currently used |

### Config quirks

- `pod_network_cidr` is **not** reset by `reset_setup_configuration()` (zeroing it broke subsequent runs — preserved by design).
- The interactive menu writes temp files under `/tmp/`, then `configure_multi_master_setup()` syncs them into `setup.conf`.
- For single-node: LB port must differ from 6443 (use 6643). LB + first master on same machine.

---

## Kubernetes

- **Version**: v1.36 from `pkgs.k8s.io/core:/stable:/v1.36/deb/` with `signed-by` GPG keyring.
- **Pinned**: `kubelet`, `kubeadm`, `kubectl` are `apt-mark hold` after install (pin priority 1001 via `/etc/apt/preferences.d/kubernetes.pref`).
- **Containerd** is the only CRI runtime. Docker is not used — `install-docker.sh` is a no-op.
- `install-kubeadm.sh` installs containerd if missing (bare Ubuntu).

---

## Load balancers

| LB | Package source | Config | Notes |
|---|---|---|---|
| **HAProxy** | Debian/Ubuntu apt | `/etc/haproxy/haproxy.cfg` — TCP `server` lines | Simplest, smallest |
| **NGINX** | official nginx.org repo | `/etc/nginx/nginx.conf` — `stream` block | Version from nginx.org, not distro |
| **Envoy** | `apt.envoyproxy.io` | YAML template → rendered → systemd | Most configurable, heaviest |

All three are TCP reverse proxies forwarding to the master's kube-apiserver port (6443).

### Single-node
LB port must differ from 6443 (use 6643). LB and master are on the same machine.

---

## Calico CNI

Calico v3.32.1 is the only CNI plugin. The install script (`install-cni-pluggin.sh` — note the typo in the filename):

1. Downloads the manifest from `raw.githubusercontent.com/projectcalico/calico/v3.32.1/manifests/calico.yaml`
2. Swaps `CALICO_IPV4POOL_IPIP` from `"Always"` to `"Never"` (IPIP is blocked by most clouds)
3. Swaps `CALICO_IPV4POOL_VXLAN` from `"Never"` to `"Always"` (VXLAN over UDP 4789 works everywhere)
4. Applies the modified manifest

To replace Calico, swap `install-cni-pluggin.sh` for a different CNI manifest.

---

## Script reference

| Script | Purpose |
|---|---|
| `k8s_mcp_server.py` | MCP server entrypoint (see Quick start — MCP) |
| `cluster.sh` | Interactive menu entrypoint (see Quick start — CLI) |
| `launch-cluster.sh` | Orchestrator — validates, installs LB, runs scripts on each node |
| `kube-remove.sh` | Nuke existing K8s on a node (iptables, containerd, apt purge — safe to re-run) |
| `install-kubeadm.sh` | Install kubelet/kubeadm/kubectl + containerd + kernel config |
| `kubeadm-init.sh` | Template (placeholders replaced at runtime) |
| `prepare-cluster-join.sh` | Extract join commands from init log |
| `install-cni-pluggin.sh` | Apply Calico manifest (VXLAN mode) |
| `init-self.sh` | Download kubectl + copy kubeconfig to controller |
| `test-commands.sh` | Smoke test — nginx deployment |
| `cleanup-all.sh` | Full nuclear teardown (auto-cleans remote nodes via SSH) |
| `clean-trash.sh` | Remove temp files (unless `$debug` is set) |
| `copy-kube-config.sh` | Sync kubeconfig between controller and masters |
| `copy-init-log.sh` | Fetch init log from remote master |
| `console.sh` | Interactive bash within menu (`exit` to return) |
| `confirm-action.sh` | Generic y/n prompt |
| `install-docker.sh` | **No-op** — Docker is not used |
| `utils.sh` | Shared helpers (sourced by every script) |
| `haproxy/*.sh` | HAProxy install/configure/start/stop |
| `nginx/*.sh` | NGINX install/configure/start/stop |
| `envoy/*.sh`, `envoy/install-envoy.script` | Envoy install/configure/start/stop (note `.script` extension) |

---

## Extending

### Script conventions

- All scripts use `. script.sh` sourcing, not `bash script.sh`. This ensures variables set by `read_setup()` (auto-called from `utils.sh` at line 23) are available to the sourcing script.
- The `_ret()` helper detects context: `return 1` when sourced, `exit 1` when executed directly. Use `_ret` in error paths in `launch-cluster.sh` to work correctly in both modes.
- `utils.sh` auto-calls `"read_setup"` at line 23 — sourcing it immediately reads `setup.conf` and exports vars.

### Remote operations

- `remote_script <host> <file>` — runs a local script on remote via SSH stdin.
- `remote_cmd <host> <args>` — runs one command on remote.
- `remote_copy <src> <dst>` — SCP with `StrictHostKeyChecking=no`.
- **Remote redirects**: `remote_cmd $host "echo ... | sudo tee -a /etc/file"` — bare `>>` runs on the controller, not the remote host.
- `quiet=yes` env var suppresses SSH output in validation functions (used internally by `can_access_address`, `validate_single_master_configuration`, etc.).

### sudo patterns

- `sudo tee -a` for appending to protected files (`sudo echo >>` doesn't work — the redirect runs as user).
- `sudo -n` is used by the MCP server (non-interactive). The server auto-confirms prompts via `input="y\n"` to `launch-cluster.sh`.

---

## Tests & debugging

### Test commands

```bash
# Single-node end-to-end (envoy, nginx, or haproxy)
bash tests/e2e-single-node.sh [lb_type]

# Multi-node (requires setup.conf with workers)
bash tests/e2e-multi-node.sh [iterations]

# Stress test (default 20 iterations)
bash tests/test.sh [count]
```

### Test details

- `tests/e2e-single-node.sh` runs `bash -c ". script.sh"` per step to isolate sourced scripts and prevent exit-code leaks. Does NOT tear down — the cluster is left running for inspection.
- `tests/e2e-multi-node.sh` builds a multi-node cluster, verifies cross-node pod HTTP connectivity in both directions, then tears down. Requires `setup.conf` with workers.
- `tests/test.sh` stress tests by repeating install/teardown with random LB types (default 20 iterations).

### Debug mode

```bash
debug=yes sudo ./cluster.sh
```

Preserves temp files and enables verbose `debug()` print calls.

---

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

# Full nuclear teardown (auto-cleans remote nodes via SSH)
sudo bash cleanup-all.sh

# Drop into interactive bash from the menu (exit to return)
# (select Console from menu)
```

---

## Troubleshooting

### SSH: "is not accessible" / permission denied
```
$lb_address is not accessible. Has this machine's ssh key been added to $lb_address?
```

```bash
ssh-keygen -R <remote-ip>
ssh-copy-id <user>@<remote-ip>
```

### LB port conflicts with kube-apiserver
```
Loadbalancer address collides with ip $_ip yet loadbalancer port is 6443
```

Choose an LB port > 1000 that does not collide with 6443.

### Pods stuck in ContainerCreating / Pending

1. Check Calico pods: `kubectl -n kube-system get pods | grep calico`
2. Wait up to 30s for nodes to become Ready
3. Un-taint control-plane: `kubectl taint nodes --all node-role.kubernetes.io/control-plane-`
4. If IPIP is still active: `kubectl patch ippool default-ipv4-ippool --type merge -p '{"spec":{"ipipMode":"Never","vxlanMode":"Always"}}'`

### kubelet fails to start

```bash
sudo journalctl -u kubelet --no-pager -n 50
```

Common causes: swap enabled (`sudo swapoff -a`), cgroup driver mismatch, containerd not running.

### Cross-node pod networking fails

1. Verify both nodes `Ready`: `kubectl get nodes`
2. Check Calico running on both: `kubectl -n kube-system get pods -o wide | grep calico-node`
3. Check IP pool mode: `kubectl get ippools -o yaml | grep -E "ipipMode|vxlanMode"`
4. Check VXLAN routes: `ip route | grep vxlan`

### Re-running after failure

Safe to re-run. `kube-remove.sh` runs on every node before installing:
- `kubeadm reset --force`, purge kubelet/kubeadm/kubectl packages
- Reset containerd (wipe, regenerate config with `SystemdCgroup=true`, restart)
- Flush iptables, kill orphan processes
- Remove K8s apt repos, keyrings, sysctl configs, modules-load configs

### Clean teardown

```bash
sudo bash cleanup-all.sh
```

Does everything `kube-remove.sh` does, plus:
- Stops/purges the LB (haproxy/nginx/envoy), removes LB repos and keyrings
- Auto-cleans all remote masters and workers via SSH (iterates `$masters` and `$workers` from `setup.conf`)
- Removes temp files

No manual remote cleanup needed.

### Cheatsheet of gotchas

| Gotcha | Detail |
|---|---|
| Sourcing vs execution | Scripts use `. script.sh`, not `bash script.sh`. `_ret()` handles both. |
| sed delimiter | Use `\|` not `/` for `#pod_network_cidr#` (CIDR contains `/`) |
| Remote redirects | `>>` runs on controller. Use `echo ... \| sudo tee -a` on remote. |
| SSH key | Controller key must be in `~/.ssh/authorized_keys` on every remote node |
| Passwordless sudo | Required on all nodes (controller and remote) |
| Same SSH user | All nodes need the same SSH username (or use `~/.ssh/config` `User`) |
| containerd | Only CRI runtime. Docker is not used. `install-docker.sh` is no-op. |
| K8s pinned | `apt-mark hold kubelet kubeadm kubectl` after install |
| Calico filename | Typo in filename: `install-cni-pluggin.sh` (double `g`) |
| Envoy extension | `install-envoy.script` uses `.script` not `.sh` |
| pod_network_cidr | Not reset by `reset_setup_configuration()` — intentional |
| iptables path | `/usr/sbin/iptables` — script uses `command -v` to find it |
| pgrep truncation | `pgrep -f` for processes with names >15 chars (e.g. kube-controller-manager) |
| Held packages | `apt purge` needs `--allow-change-held-packages` |

---

## Reference

Full installer documentation: [INSTALLER.md](./INSTALLER.md) — covers pipeline steps, template engine, remote execution model, load balancer configs, menu reference, `setup.conf` reference, script reference table, and detailed troubleshooting.

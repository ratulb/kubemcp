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

## MCP tools

`opencode.json` in the project root registers the MCP server automatically. OpenCode loads these tools:

| Tool | Description |
|---|---|
| `write_config` | Write cluster config to `setup.conf` (validates inputs) |
| `read_config` | Read current `setup.conf` |
| `create_cluster` | Build the full cluster — config, LB, kubeadm init, CNI, join nodes |
| `destroy_cluster` | Full nuclear teardown — LB + k8s + repos + remote nodes |
| `get_cluster_status` | Node status + all pods |

**Self-bootstrapping**: The server creates a `.venv` and `pip install mcp` if the `mcp` module is missing.

### Example usage

```
write_config masters="localhost" workers="" loadbalancer="localhost" lb_type="haproxy" lb_port="6643" pod_network_cidr="192.168.0.0/16"
create_cluster
get_cluster_status
destroy_cluster
```

> **Single-node caveat**: LB port must differ from 6443 (use 6643). LB runs on the same machine as the first master.

---

## Quick start (CLI)

```bash
git clone https://github.com/ratulb/kubemcp.git
cd kubemcp
sudo ./cluster.sh
```

Follow the interactive menu:

1. **Cluster setup** → LB address:port, LB type, master IPs, worker IPs
2. **Launch** — press `y` when prompted

In 2–3 minutes you have a running cluster with `kubectl` on the controller.

---

## Prerequisites

- Controller SSH key in `~/.ssh/authorized_keys` on **every** remote node (LB, master, worker)
- Passwordless sudo for the SSH user on all nodes
- Same SSH username across all nodes (or use `~/.ssh/config` `User` directives)
- Network: all nodes reachable on ports 22, 6443, LB port; **UDP 4789** for Calico VXLAN

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

The controller is not joined to the cluster — `kubectl` is installed as a standalone binary with kubeconfig copied from the first master.

---

## Tests

```bash
# Single-node end-to-end (envoy, nginx, or haproxy)
bash tests/e2e-single-node.sh [lb_type]

# Multi-node (requires setup.conf with masters + workers)
bash tests/e2e-multi-node.sh [iterations]

# Stress test (default 20 iterations)
bash tests/test.sh [count]
```

---

## Reference

Full installer documentation: [INSTALLER.md](./INSTALLER.md)

Covers: pipeline steps, template engine, remote execution model, load balancer configs, menu reference, `setup.conf` reference, troubleshooting, script reference table, and tests.

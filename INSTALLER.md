# Installer reference

This document covers the full installer pipeline that `kubemcp` wraps. Everything here applies whether you use the MCP server or the standalone CLI (`sudo ./cluster.sh`).

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Controller                        │
│  Runs cluster.sh  ──────SSH──────►  LB (haproxy/    │
│  (interactive menu)                nginx/envoy)     │
│                                     │               │
│                   ┌─────────────────┼──────────┐    │
│                   ▼                 ▼          ▼    │
│              Master 1           Master 2..N   Worker│
│            (kubeadm init)       (join)       (join) │
│              │                                      │
│              └──► kubectl config (copied back)      │
└─────────────────────────────────────────────────────┘
```

The controller machine is **not** automatically joined to the cluster. `kubectl` is installed as a standalone binary and configured via kubeconfig copied from the first master. The controller can be the same machine as the first master (`masters=localhost`), or a completely separate machine.

---

## Pipeline

`launch-cluster.sh` orchestrates every step in order:

```
 1.  Validate SSH connectivity to every node (LB, masters, workers)
 2.  Install & configure the chosen load balancer on the LB node
 3.  For every master:
        kube-remove.sh       — nuke any existing k8s installation
        install-kubeadm.sh   — install kubelet / kubeadm / kubectl via apt
 4.  First master only:
        kubeadm-init.sh.tmp  — template rendered with real values
        prepare-cluster-join.sh  — extract join commands from log
        install-cni-pluggin.sh   — deploy Calico CNI (VXLAN mode)
 5.  Remaining masters:
        master-join-cluster.cmd
 6.  Workers:
        worker-join-cluster.cmd
 7.  init-self.sh           — download kubectl, copy kubeconfig to controller
 8.  test-commands.sh       — smoke test: deploy nginx, wait for pods
 9.  clean-trash.sh         — remove temp files (unless $debug is set)
```

---

## Template engine

`kubeadm-init.sh` is a template with placeholders replaced at runtime:

| Placeholder | Replaced with |
|---|---|
| `#masters#` | Space-separated master hostnames |
| `#lb_port#` | Chosen LB port |
| `#loadbalancer#` | LB hostname / IP |
| `#pod_network_cidr#` | Pod CIDR from `setup.conf` |

`launch-cluster.sh` copies it to `kubeadm-init.sh.tmp` and runs `sed` substitutions before sourcing it.

The join commands for additional masters and workers are extracted from the first master's `kubeadm-init.log` by `prepare-cluster-join.sh`.

---

## Remote execution model

All remote operations use three helpers from `utils.sh`:

```bash
remote_script <host> <local-file>     # Run a local script on a remote host (SSH stdin)
remote_cmd    <host> <args...>        # Run a one-shot command on a remote host
remote_copy   <src> <dst>            # SCP with StrictHostKeyChecking=no
```

There is no agent, no daemon, no configuration management tool. Everything happens via plain SSH with strict host key checking disabled (ephemeral cloud nodes).

---

## Calico CNI (VXLAN)

Calico v3.32.1 is the only CNI plugin. The install script:

1. Downloads the manifest
2. Swaps `CALICO_IPV4POOL_IPIP` from `"Always"` to `"Never"`
3. Swaps `CALICO_IPV4POOL_VXLAN` from `"Never"` to `"Always"`
4. Applies the modified manifest

IPIP (protocol 4) is blocked by most cloud providers. VXLAN (UDP 4789) passes through all major cloud firewalls.

To replace Calico, replace `install-cni-pluggin.sh` with a different CNI manifest.

---

## Load balancers

| LB | Package source | Config | Notes |
|---|---|---|---|
| **HAProxy** | Debian/Ubuntu apt | `/etc/haproxy/haproxy.cfg` — TCP `server` lines | Simplest, smallest |
| **NGINX** | official nginx.org repo | `/etc/nginx/nginx.conf` — `stream` block | Version from nginx.org, not distro |
| **Envoy** | `apt.envoyproxy.io` | YAML template → rendered → systemd | Most configurable, heaviest |

All three are TCP reverse proxies forwarding to the master's kube-apiserver port (6443).

**Single-node**: LB port must differ from 6443 (use 6643). LB and master are on the same machine.

---

## Menu reference

`cluster.sh` presents this menu:

| # | Option | What it does |
|---|---|---|
| 1 | **Cluster setup** | Configure LB address/port/type, master IPs, worker IPs |
| 2 | **Kubelet status** | `systemctl status kubelet` on each master |
| 3 | **System pod status** | `kubectl -n kube-system get pods` |
| 4 | **LB status** | Check LB service status on the LB node |
| 5 | **Console** | Drop into interactive bash (`exit` to return) |
| 6 | **!! Full cleanup** | Nuclear teardown |
| 7 | **Refresh** | Re-read config and refresh display |
| 8 | **Quit** | Exit |

### Setup flow

```
 1. Enter LB address:port (e.g. localhost:6643)
 2. Select LB type (haproxy/nginx/envoy)
 3. Enter master IPs (one per line, blank=done)
 4. Enter worker IPs (same pattern)
 5. Review config → Press 'y' to launch
```

All inputs are written to temp files under `/tmp/`, then `configure_multi_master_setup()` syncs them into `setup.conf`.

---

## `setup.conf` reference

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

You can edit this file directly instead of using the menu.

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

### Debug mode

```bash
debug=yes sudo ./cluster.sh
```

Preserves temp files and enables verbose `debug()` print calls.

### Re-running after failure

Safe to re-run. `kube-remove.sh` runs on every node before installing:
- `kubeadm reset --force`
- Purges kubeadm/kubelet/kubectl packages
- Resets containerd (wipe, regenerate config, restart)
- Flushes iptables, kills orphan processes
- Removes K8s apt repos, keyrings, sysctl configs

### Clean teardown

```bash
sudo bash cleanup-all.sh
```

Does everything `kube-remove.sh` does, plus stops/purges the LB, removes LB repos and keyrings, cleans all remote nodes, removes temp files.

---

## Script reference

| Script | Purpose |
|---|---|
| `cluster.sh` | Interactive menu entrypoint |
| `launch-cluster.sh` | Orchestrator — validates, installs LB, runs scripts on each node |
| `kube-remove.sh` | Nuke existing K8s on a node |
| `install-kubeadm.sh` | Install kubelet/kubeadm/kubectl + containerd |
| `kubeadm-init.sh` | Template (placeholders replaced at runtime) |
| `prepare-cluster-join.sh` | Extract join commands from init log |
| `install-cni-pluggin.sh` | Apply Calico manifest (VXLAN mode) |
| `init-self.sh` | Download kubectl + copy kubeconfig to controller |
| `test-commands.sh` | Smoke test — nginx deployment |
| `cleanup-all.sh` | Full nuclear teardown |
| `clean-trash.sh` | Remove temp files (unless `$debug`) |
| `copy-kube-config.sh` | Sync kubeconfig between controller and masters |
| `copy-init-log.sh` | Fetch init log from remote master |
| `console.sh` | Interactive bash within menu |
| `confirm-action.sh` | Generic y/n prompt |
| `install-docker.sh` | **No-op** — Docker is not used |
| `utils.sh` | Shared helpers (sourced by every script) |
| `haproxy/*.sh` | HAProxy install/configure/start/stop |
| `nginx/*.sh` | NGINX install/configure/start/stop |
| `envoy/*.sh` | Envoy install/configure/start/stop |

---

## Tests

| Script | Intent |
|---|---|
| `tests/e2e-single-node.sh [lb_type]` | Fastest regression — full pipeline on one machine. Cluster left running. |
| `tests/e2e-multi-node.sh [iterations]` | Cross-node pod networking test (build → test bidirectional HTTP → teardown) |
| `tests/test.sh [count]` | Stress test — random LB, repeat install/teardown (default 20 iterations) |

---

## File layout

```
kubemcp/
├── cluster.sh                 # ← CLI entrypoint
├── launch-cluster.sh          # Orchestrator
├── k8s_mcp_server.py          # ← MCP server entrypoint
├── opencode.json              # MCP registration
├── setup.conf                 # Configuration
├── utils.sh                   # Shared helpers
├── kube-remove.sh
├── install-kubeadm.sh
├── kubeadm-init.sh            # Template
├── prepare-cluster-join.sh
├── install-cni-pluggin.sh     # Calico
├── init-self.sh
├── test-commands.sh
├── cleanup-all.sh
├── clean-trash.sh
├── copy-kube-config.sh
├── copy-init-log.sh
├── console.sh
├── confirm-action.sh
├── install-docker.sh          # Legacy no-op
├── haproxy/                   # HAProxy scripts
├── nginx/                     # NGINX scripts
├── envoy/                     # Envoy scripts
├── tests/
│   ├── e2e-single-node.sh
│   ├── e2e-multi-node.sh
│   └── test.sh
└── nginx-deployment.yaml
```

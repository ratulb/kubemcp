#!/usr/bin/env python3
"""MCP server for kubemcp — provision Kubernetes clusters via MCP."""

import asyncio
import json
import os
import re
import subprocess
import sys

# --- Self-bootstrapping: ensure 'mcp' is available ---
_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
_VENV_DIR = os.path.join(_PROJECT_DIR, ".venv")
_VENV_PYTHON = os.path.join(_VENV_DIR, "bin", "python3")

try:
    import mcp
except ModuleNotFoundError:
    if not os.path.isfile(_VENV_PYTHON):
        subprocess.run([sys.executable, "-m", "venv", _VENV_DIR], check=True)
        subprocess.run([_VENV_PYTHON, "-m", "pip", "install", "mcp"], check=True)
    os.execv(_VENV_PYTHON, [_VENV_PYTHON, __file__, *sys.argv[1:]])

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
SETUP_CONF = os.path.join(PROJECT_DIR, "setup.conf")

server = Server("kubemcp")


def _sudo_run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a command with sudo -n. Raises on non-zero exit."""
    full_cmd = ["sudo", "-n"] + cmd
    default = {"cwd": PROJECT_DIR, "capture_output": True, "text": True, "timeout": 600}
    default.update(kwargs)
    return subprocess.run(full_cmd, **default, check=False)


def _read_setup_conf() -> dict[str, str]:
    conf: dict[str, str] = {}
    if not os.path.isfile(SETUP_CONF):
        return conf
    with open(SETUP_CONF) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                conf[k.strip()] = v.strip()
    return conf


def _write_setup_conf(**kwargs: str) -> dict[str, str]:
    """Write key=value pairs into setup.conf. Preserves existing keys not in kwargs."""
    conf = _read_setup_conf()
    conf.update({k: v for k, v in kwargs.items() if v is not None})
    lines = []
    for k, v in conf.items():
        lines.append(f"{k}={v}")
    with open(SETUP_CONF, "w") as f:
        f.write("\n".join(lines) + "\n")
    return conf


def _validate_config(masters: str, workers: str, loadbalancer: str | None, lb_port: str | None,
                     lb_type: str | None) -> str | None:
    """Validate cluster config. Returns an error string or None."""
    if not masters.strip():
        return "masters is required"
    if loadbalancer and not re.match(r"^[\w\.\-]+$", loadbalancer.strip()):
        return f"invalid loadbalancer address: {loadbalancer}"
    if lb_port:
        if not lb_port.isdigit() or not (1000 <= int(lb_port) <= 65535):
            return f"lb_port must be 1000-65535, got {lb_port}"
    if lb_type and lb_type not in ("haproxy", "nginx", "envoy"):
        return f"lb_type must be haproxy, nginx, or envoy, got {lb_type}"
    return None


def _cluster_up() -> bool:
    """Quick check: does kubectl exist and respond?"""
    try:
        r = subprocess.run(["kubectl", "get", "nodes", "--no-headers"],
                           capture_output=True, text=True, timeout=15, cwd=PROJECT_DIR)
        return r.returncode == 0
    except Exception:
        return False


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="write_config",
            description="Write cluster configuration to setup.conf. Validates inputs before writing.",
            inputSchema={
                "type": "object",
                "properties": {
                    "masters": {"type": "string", "description": "Space-separated master hostnames/IPs (e.g. 'localhost' or 'm1 m2')"},
                    "workers": {"type": "string", "description": "Space-separated worker hostnames/IPs (empty string for single-node)"},
                    "loadbalancer": {"type": "string", "description": "LB hostname or IP (omit for single-node without LB)"},
                    "lb_type": {"type": "string", "enum": ["haproxy", "nginx", "envoy"], "description": "Load balancer type"},
                    "lb_port": {"type": "string", "description": "LB listen port (e.g. 6643 for single-node, must differ from 6443)"},
                    "pod_network_cidr": {"type": "string", "description": "Pod CIDR (e.g. 192.168.0.0/16)"},
                },
                "required": ["masters", "workers"],
            },
        ),
        Tool(
            name="read_config",
            description="Read the current setup.conf and return all key-value pairs.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="create_cluster",
            description="Build the full cluster: writes config if provided, then runs launch-cluster.sh. Use write_config first if you want to inspect the config before launching.",
            inputSchema={
                "type": "object",
                "properties": {
                    "masters": {"type": "string", "description": "Space-separated master hostnames/IPs"},
                    "workers": {"type": "string", "description": "Space-separated worker hostnames/IPs"},
                    "loadbalancer": {"type": "string", "description": "LB hostname or IP"},
                    "lb_type": {"type": "string", "enum": ["haproxy", "nginx", "envoy"]},
                    "lb_port": {"type": "string", "description": "LB listen port"},
                    "pod_network_cidr": {"type": "string", "description": "Pod CIDR"},
                },
                "required": ["masters", "workers"],
            },
        ),
        Tool(
            name="destroy_cluster",
            description="Full nuclear teardown: stops LB, removes Kubernetes, purges repos on all nodes. Runs cleanup-all.sh.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="get_cluster_status",
            description="Returns node status and all pods if a cluster is running, or a message if no cluster is detected.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "read_config":
        conf = _read_setup_conf()
        return [TextContent(type="text", text=json.dumps(conf, indent=2))]

    if name == "write_config":
        err = _validate_config(
            arguments.get("masters", ""),
            arguments.get("workers", ""),
            arguments.get("loadbalancer"),
            arguments.get("lb_port"),
            arguments.get("lb_type"),
        )
        if err:
            return [TextContent(type="text", text=f"error: {err}")]
        _write_setup_conf(**arguments)
        return [TextContent(type="text", text="config written")]

    if name == "create_cluster":
        cfg = {k: v for k, v in arguments.items() if v is not None}
        err = _validate_config(
            cfg.get("masters", ""),
            cfg.get("workers", ""),
            cfg.get("loadbalancer"),
            cfg.get("lb_port"),
            cfg.get("lb_type"),
        )
        if err:
            return [TextContent(type="text", text=f"error: {err}")]
        if cfg:
            _write_setup_conf(**cfg)
        r = _sudo_run(["bash", "launch-cluster.sh"], input="y\n", timeout=600)
        out = r.stdout + "\n" + r.stderr
        if r.returncode != 0:
            return [TextContent(type="text", text=f"cluster build failed (exit {r.returncode}):\n{out}")]
        return [TextContent(type="text", text=f"cluster built successfully:\n{out}")]

    if name == "destroy_cluster":
        r = _sudo_run(["bash", "cleanup-all.sh"], timeout=300)
        out = r.stdout + "\n" + r.stderr
        if r.returncode != 0:
            return [TextContent(type="text", text=f"teardown failed (exit {r.returncode}):\n{out}")]
        return [TextContent(type="text", text=f"cluster destroyed:\n{out}")]

    if name == "get_cluster_status":
        if not _cluster_up():
            return [TextContent(type="text", text="no cluster detected (kubectl not available or not responding)")]
        r = subprocess.run(
            ["kubectl", "get", "nodes", "-o", "wide"],
            capture_output=True, text=True, timeout=30, cwd=PROJECT_DIR,
        )
        nodes = r.stdout + r.stderr
        r2 = subprocess.run(
            ["kubectl", "get", "pods", "-A"],
            capture_output=True, text=True, timeout=30, cwd=PROJECT_DIR,
        )
        pods = r2.stdout + r2.stderr
        return [TextContent(type="text", text=f"--- Nodes ---\n{nodes}\n--- Pods ---\n{pods}")]

    return [TextContent(type="text", text=f"unknown tool: {name}")]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())

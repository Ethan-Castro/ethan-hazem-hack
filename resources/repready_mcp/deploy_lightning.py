#!/usr/bin/env python3
"""Deploy the RepReady MCP server to Lightning AI as a Deployment (public URL).

Usage:
    pip install lightning-sdk
    export LIGHTNING_USER_ID=...        # never commit these
    export LIGHTNING_API_KEY=...
    python deploy_lightning.py

Requires the target teamspace to have available balance/credits — Lightning returns
HTTP 400 "insufficient balance to start the cloud space" otherwise (top up first).

The script: ensures a build Studio exists, uploads this folder, then starts a
single-replica CPU Deployment running `server.py`. It prints the public MCP
endpoint (`<url>/mcp`) on success and stops the build Studio to save cost.
Override the constants below or via env (TEAMSPACE, OWNER, DEPLOY_NAME, PORT).
"""
from __future__ import annotations

import os
import time
import traceback
from pathlib import Path

from lightning_sdk import Deployment, Machine, Studio, Teamspace, User
from lightning_sdk.api.deployment_api import AutoScaleConfig, HttpHealthCheck

LOCAL_CODE = str(Path(__file__).parent)
TEAMSPACE = os.environ.get("TEAMSPACE", "hyrox")
OWNER = os.environ.get("OWNER", "theethancastro")
NAME = os.environ.get("DEPLOY_NAME", "repready-mcp")
PORT = int(os.environ.get("PORT", "8000"))


def main() -> None:
    if not (os.environ.get("LIGHTNING_USER_ID") and os.environ.get("LIGHTNING_API_KEY")):
        raise SystemExit("Set LIGHTNING_USER_ID and LIGHTNING_API_KEY env vars first.")

    ts = Teamspace(name=TEAMSPACE, user=User(name=OWNER))
    print(f"[1/5] teamspace {TEAMSPACE} ({ts.id})")

    studio = Studio(name=NAME, teamspace=ts, create_ok=True)
    print(f"[2/5] studio '{studio.name}' status={studio.status}")
    if str(studio.status) not in ("Status.Running", "running"):
        print("       starting studio (CPU_SMALL)…")
        studio.start(machine=Machine.CPU_SMALL)

    print("[3/5] uploading code → ~/repready_mcp")
    studio.upload_folder(folder_path=LOCAL_CODE, remote_path="repready_mcp", progress_bar=False)

    print("[4/5] starting deployment…")
    dep = Deployment(name=NAME, teamspace=ts)
    cmd = f"cd ~/repready_mcp && pip install -q -r requirements.txt && PORT={PORT} python server.py"
    try:
        dep.start(
            studio=studio,
            machine=Machine.CPU_SMALL,
            ports=[PORT],
            command=cmd,
            health_check=HttpHealthCheck(path="/health", port=PORT, initial_delay_seconds=25),
            autoscale=AutoScaleConfig(min_replicas=1, max_replicas=1, metric="CPU", threshold=90),
            replicas=1,
        )
    except Exception:
        print("start() raised (may already exist) — continuing to poll:")
        traceback.print_exc()

    print("[5/5] waiting for a running replica + public URL…")
    url = None
    for i in range(60):  # ~5 min
        urls = getattr(dep, "urls", None) or []
        running = getattr(dep, "running_replicas", None)
        if urls:
            url = urls[0] if isinstance(urls, (list, tuple)) else urls
            print(f"   t+{i * 5}s running={running} urls={urls}")
            if running:
                break
        else:
            print(f"   t+{i * 5}s running={running} (no url yet)")
        time.sleep(5)

    print("\n=== RESULT ===")
    print("deployment urls:", getattr(dep, "urls", None))
    if url:
        base = url.rstrip("/")
        print("MCP ENDPOINT (use in Claude / GraphN):", base + "/mcp")
        print("HEALTH:", base + "/health")

    try:
        studio.stop()
        print("build studio stopped (deployment runs independently).")
    except Exception as e:
        print("studio stop note:", e)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Deploy the RepReady BRIDGE to Lightning AI (the MCP Claude adds as a connector).

The bridge fronts the GraphN workflow. It needs the GraphN run config as deployment
env vars — passed through from your shell (never committed):
    export LIGHTNING_USER_ID=…  LIGHTNING_API_KEY=…
    export GRAPHN_API_KEY=gn_…  GRAPHN_WORKSPACE=ws_…  GRAPHN_WORKFLOW_ID=wf_…
    python deploy_lightning.py
Prints the public <url>/mcp endpoint. Reuses the existing 'repready-mcp' build Studio.
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
STUDIO_NAME = os.environ.get("STUDIO_NAME", "repready-mcp")  # reuse the existing build studio
NAME = os.environ.get("DEPLOY_NAME", "repready-bridge")
PORT = int(os.environ.get("PORT", "8000"))

REQUIRED = ["LIGHTNING_USER_ID", "LIGHTNING_API_KEY", "GRAPHN_API_KEY", "GRAPHN_WORKSPACE", "GRAPHN_WORKFLOW_ID"]


def main() -> None:
    missing = [k for k in REQUIRED if not os.environ.get(k)]
    if missing:
        raise SystemExit(f"Set these env vars first: {', '.join(missing)}")

    deploy_env = {
        "GRAPHN_URL": os.environ.get("GRAPHN_URL", "https://cp.graphn.ai"),
        "GRAPHN_WORKSPACE": os.environ["GRAPHN_WORKSPACE"],
        "GRAPHN_WORKFLOW_ID": os.environ["GRAPHN_WORKFLOW_ID"],
        "GRAPHN_API_KEY": os.environ["GRAPHN_API_KEY"],
    }

    ts = Teamspace(name=TEAMSPACE, user=User(name=OWNER))
    print(f"[1/4] teamspace {TEAMSPACE} ({ts.id})")

    studio = Studio(name=STUDIO_NAME, teamspace=ts, create_ok=True)
    if str(studio.status) not in ("Status.Running", "running"):
        print("       starting build studio (CPU_SMALL)…")
        studio.start(machine=Machine.CPU_SMALL)
    print(f"[2/4] studio '{studio.name}' status={studio.status}")

    print("[3/4] uploading bridge code → ~/repready_bridge")
    studio.upload_folder(folder_path=LOCAL_CODE, remote_path="repready_bridge", progress_bar=False)

    print("[4/4] starting deployment (env: GRAPHN_* injected)…")
    dep = Deployment(name=NAME, teamspace=ts)
    cmd = f"cd ~/repready_bridge && pip install -q -r requirements.txt && PORT={PORT} python server.py"
    try:
        dep.start(
            studio=studio, machine=Machine.CPU_SMALL, ports=[PORT], command=cmd, env=deploy_env,
            health_check=HttpHealthCheck(path="/health", port=PORT, initial_delay_seconds=25),
            autoscale=AutoScaleConfig(min_replicas=1, max_replicas=1, metric="CPU", threshold=90), replicas=1,
        )
    except Exception:
        print("start() raised (may already exist) — continuing to poll:")
        traceback.print_exc()

    url = None
    for i in range(60):
        urls = getattr(dep, "urls", None) or []
        running = getattr(dep, "running_replicas", None)
        if urls:
            url = urls[0] if isinstance(urls, (list, tuple)) else urls
            print(f"   t+{i*5}s running={running} urls={urls}")
            if running:
                break
        else:
            print(f"   t+{i*5}s running={running} (no url yet)")
        time.sleep(5)

    print("\n=== RESULT ===")
    if url:
        print("BRIDGE MCP ENDPOINT (add to Claude):", url.rstrip("/") + "/mcp")
        print("HEALTH:", url.rstrip("/") + "/health")
    try:
        studio.stop()
        print("build studio stopped.")
    except Exception as e:
        print("studio stop note:", e)


if __name__ == "__main__":
    main()

# RepReady MCP — Deploy to Lightning AI

Get a public HTTPS MCP endpoint for the RepReady HYROX training-coach connector running on Lightning AI, then wire it into Claude as a custom connector.

---

## 1. Prerequisites

- A [Lightning AI](https://lightning.ai) account **with available balance/credits**. Starting any machine (Studio or Deployment) fails with `HTTP 400: insufficient balance to start the cloud space` if the teamspace has no credit — top up first.
- This folder (`repready_mcp/`) with [`server.py`](server.py), [`requirements.txt`](requirements.txt), and [`deploy_lightning.py`](deploy_lightning.py) present.
- Python 3.11+ (Lightning Studios ship with it by default).

> **Endpoint path:** the MCP endpoint is `…/mcp` (**no** trailing slash). This server serves `/mcp` directly; `/mcp/` 307-redirects to it. Use the no-slash form in Claude and GraphN.

---

## 2. Option A — Lightning AI Studio (recommended for hackathons)

This is the fastest path: spin up a Studio, drop in your code, expose the port.

### 2a. Create a Studio

1. Go to [lightning.ai](https://lightning.ai) → **Studios** → **New Studio**.
2. Choose the **Blank** (or any CPU) template. Name it `repready-mcp`.
3. Wait for the Studio to reach the **Running** state.

### 2b. Upload the server code

**Option 1 — drag-and-drop in the Studio UI:**
Open the Studio's file browser, create a folder called `repready_mcp/`, and upload `server.py` and `requirements.txt`.

**Option 2 — clone from your repo inside the Studio terminal:**
```bash
git clone https://github.com/<your-org>/health-research-graphn.git
cd health-research-graphn/resources/repready_mcp
```

### 2c. Install dependencies

Open a **Terminal** tab in the Studio and run:

```bash
pip install -r requirements.txt
```

`requirements.txt` includes at minimum `fastmcp` and `uvicorn`.

### 2d. Start the MCP server

```bash
python server.py
```

The server starts with:
```
FastMCP running on http://0.0.0.0:8000
MCP endpoint: http://0.0.0.0:8000/mcp
```

Keep this terminal session alive (or run it with `nohup python server.py &` if you need to close the tab).

### 2e. Expose the port to get a public HTTPS URL

1. In the Lightning Studio UI, click the **Ports** (or **Share Port**) button — usually in the top bar or the left panel.
2. Enter port **`8000`** and click **Expose** (or **Share**).
3. Lightning generates a public HTTPS URL, e.g.:  
   `https://repready-mcp-<hash>.lightning.ai`

Your **public MCP endpoint** is that host with `/mcp` appended:

```
https://repready-mcp-<hash>.lightning.ai/mcp
```

> Save this URL — you will paste it into Claude in Step 6.

---

## 3. Option B — Lightning Deployment via SDK (one command, autoscaling URL)

This is the scripted path used for RepReady: a single-replica **CPU Deployment** with a
stable public URL that won't sleep. The script [`deploy_lightning.py`](deploy_lightning.py)
does it end to end.

```bash
pip install lightning-sdk
export LIGHTNING_USER_ID=<your-user-id>     # never commit these
export LIGHTNING_API_KEY=<your-api-key>
python deploy_lightning.py                  # teamspace defaults to "hyrox"
```

What it does: ensures a build Studio (`repready-mcp`) exists in the teamspace, uploads this
folder, starts a `Deployment` running `server.py` on port 8000 with a `/health` check, polls
until a replica is live, prints the public **`<url>/mcp`** endpoint, then stops the build
Studio to save cost. Override `TEAMSPACE` / `OWNER` / `DEPLOY_NAME` / `PORT` via env.

> Requires teamspace balance. If you see `HTTP 400: insufficient balance to start the cloud
> space`, top up credits in the Lightning console and re-run — nothing else changes.

---

## 4. Verify the Endpoint

Before adding it to Claude, confirm the server is reachable and speaking MCP correctly.

**Quick check with mcp-remote (Node.js required):**

```bash
npx mcp-remote https://repready-mcp-<hash>.lightning.ai/mcp
```

A successful connection prints the server's tool list.

**Alternative — MCP Inspector:**

```bash
npx @modelcontextprotocol/inspector https://repready-mcp-<hash>.lightning.ai/mcp
```

Open the Inspector UI in your browser and verify you can see the RepReady tools listed.

If the connection fails, check:
- The Studio is still **Running** and the terminal session with `python server.py` is active.
- Port `8000` is exposed (Lightning Ports panel).
- The URL ends with `/mcp` (no trailing slash; `/mcp/` 307-redirects).

---

## 5. Add to Claude as a Custom Connector

### Claude.ai (web)

1. Go to [claude.ai](https://claude.ai) → **Settings** → **Connectors**.
2. Click **Add custom connector**.
3. Paste your public MCP URL:  
   `https://repready-mcp-<hash>.lightning.ai/mcp`
4. Leave auth as **None** (no-auth — see security note below).
5. Save. Claude will discover RepReady's tools automatically.

### Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "repready": {
      "url": "https://repready-mcp-<hash>.lightning.ai/mcp"
    }
  }
}
```

Restart Claude Desktop. The RepReady connector and any MCP Apps UI cards will appear.

> **MCP Apps UI:** the server also serves HTML resources under a `ui://` scheme. These render as interactive cards directly inside Claude Desktop and claude.ai when the connector is active.

---

## 6. Security Checklist

| Item | Status |
|------|--------|
| **No-auth is hackathon-only.** The server runs open with no authentication. Anyone with the URL can call its tools. | ⚠️ Acceptable for a 48-hour hackathon; must be fixed before any public launch. |
| **Production auth.** Claude supports [Dynamic Client Registration (DCR)](https://claude.ai/api/mcp/auth_callback) and the standard OAuth 2.1 callback at `https://claude.ai/api/mcp/auth_callback`. Add OAuth to `server.py` before going to production. | TODO for v1 |
| **Rotate your Lightning API key** after the hackathon ends. Anyone who saw your terminal history or logs could reuse it. | Do this immediately post-event. |
| **Never commit secrets.** Do not commit `.env` files, `LIGHTNING_API_KEY`, or any token to git. Add `.env` to `.gitignore` if it is not already there. | Keep this permanently. |
| **Shut down the Studio** when you are done. An idle Studio still keeps the URL live and incurs usage. | After the event. |

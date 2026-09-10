# MCP Infrastructure Hub

> An AI that safely manages live cloud infrastructure through natural language — every action guarded, human-approved, and audited.

You type *"scale my node pool to 4 nodes"* in a chat box. Google Gemini decides which tool to call, a Python **MCP server** executes it against **Google Kubernetes Engine**, a **human approval gate** blocks the write until you click *Approve*, and every step is written to a **PostgreSQL audit log** that streams live to a **React observability dashboard** — all running on GKE with **zero credential keys**.

---

## What it does

- **Natural-language control of infrastructure.** Ask about cluster health or request a scaling change in plain English; the AI translates intent into safe, pre-defined tool calls.
- **Guarded writes (human-in-the-loop).** Every write is two-phase: the AI must first *preview* the change and receive a one-time confirmation token, then a human must *approve* it in the UI before it executes. The AI physically cannot exceed hard-coded guardrails (e.g. max node count).
- **Full audit trail.** Every proposed, executed, and declined action is logged to PostgreSQL with the original question, the tool + arguments, and a human-readable result.
- **Live observability.** A dark, single-screen dashboard shows a cluster health strip, summary stat cards, and a real-time action feed that reads like a story: *question asked → action taken → human decision → result.*
- **Keyless, production-grade auth.** In-cluster workloads authenticate to Google Cloud via Workload Identity — no service-account key files anywhere.

---

## Architecture

```
                      ┌──────────────────────────────────────────┐
   ONE BROWSER TAB    │        DASHBOARD (React + nginx)           │
                      │  ┌───────────────┐   ┌──────────────────┐ │
   You type here ────▶│  │  CHAT PANEL    │   │  HEALTH STRIP     │ │
                      │  └───────┬────────┘   ├──────────────────┤ │
   Approve / Deny ◀───│          │            │  STAT CARDS       │ │
   modal              │          │            ├──────────────────┤ │
                      │          │            │  ACTION FEED      │◀── polls every 4s
                      └──────────┼─────────────────────▲───────────┘
                    nginx proxy  │ /ai/*         /api/* │ nginx proxy
                                 ▼                      │
                      ┌────────────────────┐   ┌────────┴─────────┐
                      │  AI-HOST (pod)      │   │  AUDIT-API (pod) │
                      │  Gemini brain       │   │  read-only SQL   │
                      │  /chat  /approve    │   └────────▲─────────┘
                      └─────────┬──────────┘            │ reads
                    MCP (in-cluster service name)       │
                                ▼                        │
                      ┌────────────────────┐   ┌────────┴─────────┐
                      │  MCP-SERVER (pod)   │──▶│  POSTGRES (pod)  │
                      │  tools + GCP (WI)   │   │  + PVC (durable) │
                      └─────────┬──────────┘   └──────────────────┘
                                ▼
                          GCP / GKE (query + scale node pool)
```

**The five services**

| Service | Role | Exposure |
|---|---|---|
| `mcp-server` | The "hands" — exposes MCP tools, calls GCP via Workload Identity, writes audit rows | LoadBalancer :8000 |
| `ai-host` | The "brain" — Gemini + MCP client; `/chat` and `/approve` endpoints; tags each action with the user's question and manages the write lifecycle | ClusterIP :9000 (internal) |
| `audit-api` | Read-only FastAPI over the audit log — `/api/audit`, `/api/stats`, `/api/health` | LoadBalancer :8080 |
| `dashboard` | React SPA + nginx; chat on the left, live observability on the right; nginx proxies `/api` and `/ai` by service name | LoadBalancer :80 |
| `postgres` | Audit log store, PVC-backed, schema auto-created via ConfigMap init | ClusterIP :5432 (internal) |

---

## Request flow — "scale default-pool to 4 nodes"

1. Browser `POST /ai/chat` → **ai-host**.
2. ai-host sends the message to **Gemini**, which calls `get_gke_cluster_status` to read current state → routed to **mcp-server** → logs a `success` row.
3. Gemini calls `scale_gke_node_pool` **without** a token → mcp-server returns a preview + `confirm_token` → logs a `pending_confirmation` row.
4. Gemini calls `scale_gke_node_pool` **with** the token → ai-host **pauses** and returns `approval_required` to the browser.
5. Browser shows an **Approve / Deny modal**.
   - **Approve** → ai-host executes the tool (mcp-server scales GKE for real, logs `executed`) and deletes the stale `pending_confirmation` row.
   - **Deny** → the pending row is marked `declined` ("Declined by human reviewer"); nothing is scaled.
6. The dashboard feed and health strip update within ~4 seconds.

---

## Tech stack

| Layer | Technology |
|---|---|
| AI / brain | Google Gemini (`gemini-flash-latest`) via `google-genai` |
| Protocol | Model Context Protocol (MCP), Python SDK — `MCPServer`, Streamable HTTP transport |
| Backend | Python, FastAPI (ai-host + audit-api) |
| Database | PostgreSQL 16 (audit log), PVC-backed |
| Frontend | React (Vite) + nginx reverse proxy |
| Containerization | Docker, Docker Compose (local) |
| Infrastructure as Code | Terraform (GKE cluster + node pool) |
| Orchestration | Kubernetes (GKE), Workload Identity |
| Cloud | Google Cloud Platform (GKE, Artifact Registry, IAM) |
| CI/CD | Jenkins (build → push → deploy pipeline) |

---

## The safety model (the core idea)

Letting an AI touch infrastructure is only acceptable with defense-in-depth. This project layers four independent protections:

1. **Least-privilege tools.** The AI can only call the pre-defined tools the MCP server exposes — never arbitrary commands.
2. **Hard guardrails in code.** `scale_gke_node_pool` refuses any request outside `MIN_ALLOWED_NODES..MAX_ALLOWED_NODES`, regardless of what the AI asks. A hallucinating or compromised model still cannot over-provision or scale to zero.
3. **Two-phase confirmation.** Writes require a preview + one-time token, then explicit human approval in the UI. The token ties the approval to the exact parameters — not a blank cheque.
4. **Immutable audit log.** The chat is transient; the audit table is the permanent record of every proposed, executed, and declined action.

---

## Repository layout

```
mcp-infra-hub/
├── server/            # MCP server (tools + GCP + audit writes)
├── ai-host/           # FastAPI Gemini host (/chat, /approve)
├── api/               # read-only audit API (FastAPI)
├── dashboard/         # React SPA + nginx (chat + observability)
├── db/                # init.sql (audit schema)
├── k8s/               # Kubernetes manifests (Deployments, Services, PVC, ConfigMap)
├── terraform/         # GKE cluster as code
├── jenkins/           # custom Jenkins image + compose
├── scripts/           # bootstrap.sh (idempotent post-recreate setup)
├── docker-compose.yml # local dev stack
└── Jenkinsfile        # CI/CD pipeline
```

---

## Running locally (Docker Compose)

```bash
docker compose up -d --build
# dashboard  → http://localhost:3000
# audit-api  → http://localhost:8080
# mcp-server → http://localhost:8000/mcp
```

The MCP server can be exercised without any AI using the MCP Inspector:

```bash
npx @modelcontextprotocol/inspector
# Transport: Streamable HTTP  |  URL: http://127.0.0.1:8000/mcp
```

> Note: local host connections to Postgres use the host-mapped port (`5433`); container-to-container connections use the internal port (`5432`).

---

## Deploying to GKE

```bash
# 1. Provision the cluster (Workload Identity enabled) with Terraform
cd terraform && terraform init && terraform apply && cd ..

# 2. One-command idempotent setup: creds, namespace, secrets, KSA, manifests
export GEMINI_API_KEY=your-key
bash scripts/bootstrap.sh

# 3. Build & push images to Artifact Registry
export REPO=us-central1-docker.pkg.dev/<PROJECT_ID>/infra-hub
for svc in server:mcp-server api:audit-api ai-host:ai-host dashboard:dashboard; do
  dir=${svc%%:*}; img=${svc##*:}
  docker build -t $REPO/$img:latest ./$dir && docker push $REPO/$img:latest
done

# 4. Apply and get the one URL you present
kubectl apply -f k8s/
kubectl get svc dashboard -n infra-hub   # EXTERNAL-IP → the whole demo
```

### Workload Identity (keyless auth)

The `mcp-server` pod runs as a Kubernetes service account (`infra-hub-ksa`) annotated to impersonate a Google service account (`infra-hub-gsa`) that holds `roles/container.clusterAdmin`. The same `google.auth.default()` code path works unchanged locally (via ADC) and in-cluster (via Workload Identity) — **no key file is ever created or stored.** (Ericsson org policy blocks downloadable SA keys, which is exactly the pattern this design embraces.)

---

## CI/CD (Jenkins)

A `Jenkinsfile` pipeline automates the manual loop: **Checkout → Setup GCP → Build → Push → Deploy to GKE**, with each build uniquely tagged by `$BUILD_NUMBER` for trivial rollbacks. Jenkins runs from a custom image bundling `docker`, `gcloud`, and `kubectl`.

---

## Example prompts (demo)

**Reads**
- "What's the status of my GKE cluster in us-central1-a?"
- "How many nodes are currently running?"
- "Give me a summary — version, node count, and region."

**Writes (trigger the approval modal)**
- "Scale my default-pool to 4 nodes."
- "Scale down default-pool to 2 nodes to save cost."

**Guardrail refusal (safety demo)**
- "Scale default-pool to 50 nodes."  → refused (exceeds `MAX_ALLOWED_NODES`)
- "Scale default-pool to 0 nodes."   → refused (below `MIN_ALLOWED_NODES`)

**Agentic multi-step**
- "Check my cluster status, and if it has fewer than 3 nodes, scale it to 3."

---

## Known operational gotchas (lessons learned)

Documenting these because they shaped real design decisions:

- **LoadBalancer IPs change on cluster recreate.** The dashboard therefore calls **relative paths** (`/api`, `/ai`) and nginx proxies to backends by **in-cluster service name** — no baked-in IPs, so nothing breaks after `terraform destroy` + recreate. (React bakes URLs at build time, so hardcoding an IP was a recurring trap.)
- **`terraform destroy` wipes in-cluster state.** The namespace, secrets, and the Workload Identity KSA all vanish with the cluster. `scripts/bootstrap.sh` recreates them idempotently in one command.
- **A Deployment referencing a missing service account produces zero pods** (not an error you'd notice in `get pods` until you look). Recreating the KSA fixes it.
- **PVC survives pod restarts, not full cluster teardown.** A PersistentVolumeClaim keeps audit data across pod/redeploy cycles, but a `terraform destroy` deletes the underlying disk too. The production-grade next step is **Cloud SQL** (managed Postgres outside the cluster) so the audit trail outlives the cluster entirely.
- **MCP stdio vs. HTTP.** stdio only works for a locally-launched subprocess client; switching to the Streamable HTTP transport is what makes the server reachable by browsers, containers, and remote hosts.
- **Model availability drifts.** Pinning a specific Gemini model can break when it's retired; `gemini-flash-latest` tracks the current flash model. The model is set via the `GEMINI_MODEL` env var (no rebuild needed to change it).

---

## Roadmap

- Migrate audit storage to **Cloud SQL** for teardown-proof durability.
- Convert the Postgres Deployment to a **StatefulSet**.
- Restrict the public LoadBalancers with `loadBalancerSourceRanges` or an authenticated Ingress.
- Add a Git webhook so `git push` auto-triggers the Jenkins pipeline, plus a test stage.
- Register the deployed MCP server as a remote connector in an enterprise AI host (e.g. via OAuth) for governed, org-wide access.

---

## Why this project

It exercises the full modern platform-engineering stack — MCP, an LLM-driven agent, Kubernetes, Terraform, Workload Identity, CI/CD, and observability — around a genuinely hard problem: **giving an AI real power over infrastructure without giving up human control or auditability.** The result is a working, one-URL demonstration of safe, autonomous, fully-audited AI operations.

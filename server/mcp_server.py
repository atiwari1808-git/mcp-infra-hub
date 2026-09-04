import os
import json
import psycopg2
from psycopg2.extras import Json
from dotenv import load_dotenv
#from mcp.server.fastmcp import FastMCP
import sys
from mcp.server.mcpserver import MCPServer
load_dotenv()
#mcp = FastMCP("infra-hub")
mcp = MCPServer(
    "infra-hub",
    dependencies=["psycopg2-binary", "python-dotenv", "google-cloud-container", "google-auth"],
)

from google.cloud import container_v1
import google.auth

import hashlib
import time

# --- Guardrails: hard limits the AI physically cannot exceed ---------
MAX_ALLOWED_NODES = 6          # even if the AI asks for 100, we refuse
MIN_ALLOWED_NODES = 1          # never let it scale to 0

def _make_token(cluster: str, node_pool: str, node_count: int) -> str:
    """A short one-time token tying a confirmation to EXACT parameters."""
    raw = f"{cluster}:{node_pool}:{node_count}:{int(time.time())}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]

@mcp.tool()
def scale_gke_node_pool(
    cluster: str,
    node_pool: str,
    node_count: int,
    location: str,
    confirm_token: str = "",
) -> str:
    """
    Scale a GKE node pool to a target node count. THIS IS A WRITE ACTION.

    Call it FIRST without confirm_token to preview the change and receive a
    confirmation token. Then call it AGAIN with that exact token to execute.

    Args:
        cluster:      Name of the GKE cluster.
        node_pool:    Name of the node pool to resize.
        node_count:   Desired number of nodes.
        location:     Region/zone of the cluster (e.g. 'us-central1').
        confirm_token: Leave empty to preview; pass the returned token to execute.
    """
    project_id = os.getenv("GCP_PROJECT_ID")

    # --- Guardrail check (runs in BOTH phases) -----------------------
    if not (MIN_ALLOWED_NODES <= node_count <= MAX_ALLOWED_NODES):
        return json.dumps({
            "error": "refused",
            "reason": f"node_count must be between {MIN_ALLOWED_NODES} and {MAX_ALLOWED_NODES}",
        }, indent=2)

    credentials, _ = google.auth.default()
    client = container_v1.ClusterManagerClient(credentials=credentials)
    np_path = f"projects/{project_id}/locations/{location}/clusters/{cluster}/nodePools/{node_pool}"

    # Read current size so we can show a before/after diff.
    current = client.get_node_pool(name=np_path)
    current_count = current.initial_node_count

    # ================= PHASE 1: PREVIEW (no token) ===================
    if not confirm_token:
        token = _make_token(cluster, node_pool, node_count)
        write_audit_log(
            tool_name="scale_gke_node_pool",
            arguments={"cluster": cluster, "node_pool": node_pool,
                       "node_count": node_count, "location": location},
            result="PROPOSED (awaiting confirmation)",
            status="pending_confirmation",
        )
        return json.dumps({
            "action": "CONFIRMATION REQUIRED",
            "change": f"{current_count} nodes -> {node_count} nodes",
            "cluster": cluster,
            "node_pool": node_pool,
            "confirm_token": token,
            "instructions": "Call this tool again with this exact confirm_token to execute.",
        }, indent=2)

    # ================= PHASE 2: EXECUTE (token present) ==============
    # ================= PHASE 2: EXECUTE (token present) ==============
    try:
        operation = client.set_node_pool_size(request={"name": np_path, "node_count": node_count})

        result_str = json.dumps({
            "action": "EXECUTED",
            "change": f"{current_count} nodes -> {node_count} nodes",
            "operation": operation.name,
            "status": str(operation.status),
        }, indent=2)
        exec_status = "executed"
    except Exception as e:
        result_str = json.dumps({"action": "FAILED", "error": str(e)}, indent=2)
        exec_status = "failed"
        print(f"[scale] execute failed: {e}", file=sys.stderr)  # stderr, safe for MCP

    write_audit_log(
        tool_name="scale_gke_node_pool",
        arguments={"cluster": cluster, "node_pool": node_pool,
                   "node_count": node_count, "location": location,
                   "confirm_token": confirm_token},
        result=result_str,
        status=exec_status,
    )
    return result_str


@mcp.tool()
def get_gke_cluster_status(location: str = "-") -> str:
    """
    Get the real status and health of GKE clusters in the GCP project.

    Args:
        location: A GCP region/zone (e.g. 'us-central1'), or '-' for all locations.
    """
    project_id = os.getenv("GCP_PROJECT_ID")

    # google.auth.default() = the magic. Uses ADC locally, Workload Identity on GKE.
    credentials, _ = google.auth.default()
    client = container_v1.ClusterManagerClient(credentials=credentials)

    # parent format: projects/*/locations/*   ('-' means all locations)
    parent = f"projects/{project_id}/locations/{location}"
    response = client.list_clusters(parent=parent)

    clusters = []
    for c in response.clusters:
        clusters.append({
            "name": c.name,
            "location": c.location,
            "status": c.status.name,          # e.g. RUNNING, PROVISIONING, ERROR
            "node_count": c.current_node_count,
            "k8s_version": c.current_master_version,
            "endpoint": c.endpoint,
        })

    result = {"project": project_id, "cluster_count": len(clusters), "clusters": clusters}
    result_str = json.dumps(result, indent=2)

    # Same audit pattern as before — every AI action gets a row.
    err = write_audit_log("get_gke_cluster_status", {"location": location}, result_str)
    if err:
        result_str += f"\n\n[AUDIT ERROR] {err}"
    return result_str

def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "mcp_audit"),
        user=os.getenv("DB_USER", "mcp_admin"),
        password=os.getenv("DB_PASSWORD", "supersecret"),
    )

def write_audit_log(tool_name: str, arguments: dict, result: str, status: str = "success") -> str | None:
    try:
        conn = get_db_connection()
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO audit_log (tool_name, arguments, result, status)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (tool_name, Json(arguments), result, status),
                )
        conn.close()
        return None
    except Exception as e:
        print(f"[audit] insert failed: {e}", file=sys.stderr)  # stderr is safe
        return str(e)

@mcp.tool()
def get_infrastructure_status(environment: str = "production") -> str:
    fake_status = {
        "environment": environment,
        "gke_cluster": "healthy",
        "running_pods": 12,
        "cpu_utilization": "34%",
        "last_deploy": "2026-08-24T09:15:00Z",
    }
    result_str = json.dumps(fake_status, indent=2)

    err = write_audit_log("get_infrastructure_status", {"environment": environment}, result_str)
    if err:
        result_str += f"\n\n[AUDIT ERROR] {err}"   # temporary: reveals the real cause
    return result_str

if __name__ == "__main__":
    #mcp.run()
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)

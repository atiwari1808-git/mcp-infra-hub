import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

app = FastAPI(title="MCP Infra Hub - Audit API")

# --- CORS: let the React dev server (a different origin) call us ------
# Vite runs on :5173, this API on :8080 -> different origin -> browser
# blocks it unless we explicitly allow it here.
#app.add_middleware(
    #CORSMiddleware,
   # allow_origins=["http://localhost:5173","http://localhost:3000", "http://34.46.121.105"],
  #  allow_methods=["GET"],
 #   allow_headers=["*"],
#)
import os

# Comma-separated origins from env; falls back to permissive for the demo
_origins = os.getenv("ALLOWED_ORIGINS", "*").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["GET"],
    allow_headers=["*"],
)

def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "mcp_audit"),
        user=os.getenv("DB_USER", "mcp_admin"),
        password=os.getenv("DB_PASSWORD", "supersecret"),
        cursor_factory=RealDictCursor,   # returns rows as dicts, not tuples
    )

@app.get("/api/audit")
def get_audit_logs(limit: int = 50):
    """Return the most recent audit rows for the dashboard feed."""
    conn = get_db_connection()
    with conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, tool_name, action_type, arguments, status,
                   old_value, new_value, called_at
            FROM audit_log
            ORDER BY id DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    conn.close()
    return {"count": len(rows), "logs": rows}

@app.get("/api/stats")
def get_stats():
    """Aggregate counts for dashboard summary cards."""
    conn = get_db_connection()
    with conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS total FROM audit_log;")
        total = cur.fetchone()["total"]
        cur.execute("""
            SELECT status, COUNT(*) AS n FROM audit_log GROUP BY status;
        """)
        by_status = cur.fetchall()
    conn.close()
    return {"total_actions": total, "by_status": by_status}


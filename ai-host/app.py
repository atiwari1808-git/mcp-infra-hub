import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from pydantic import BaseModel
from dotenv import load_dotenv
from google import genai
from google.genai import types
from mcp.client.streamable_http import streamable_http_client
from mcp.client.session import ClientSession

load_dotenv()
import psycopg2

def db_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST","postgres"), port=os.getenv("DB_PORT","5432"),
        dbname=os.getenv("DB_NAME","mcp_audit"), user=os.getenv("DB_USER","mcp_admin"),
        password=os.getenv("DB_PASSWORD","supersecret"))

def _run(sql, params=(), fetch=False):
    try:
        conn = db_conn()
        with conn, conn.cursor() as cur:
            cur.execute(sql, params)
            v = cur.fetchone() if fetch else None
        conn.close()
        return v[0] if (fetch and v) else None
    except Exception as e:
        print(f"[db] {e}")
        return None

def max_id():            return _run("SELECT COALESCE(MAX(id),0) FROM audit_log", fetch=True) or 0
def tag_prompt(sid, p):  _run("UPDATE audit_log SET user_prompt=%s WHERE id>%s AND user_prompt IS NULL", (p, sid))
def pending_id(tool):    return _run("SELECT MAX(id) FROM audit_log WHERE status='pending_confirmation' AND tool_name=%s", (tool,), fetch=True)
def delete_row(rid):     _run("DELETE FROM audit_log WHERE id=%s", (rid,)) if rid else None
def mark_declined(rid):  _run("UPDATE audit_log SET status='declined', result='Declined by human reviewer' WHERE id=%s", (rid,)) if rid else None

GEMINI_KEY = os.getenv("GEMINI_API_KEY")
MCP_URL    = os.getenv("MCP_SERVER_URL", "http://mcp-server:8000/mcp")
MODEL      = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
WRITE_TOOLS = {"scale_gke_node_pool"}

gemini = genai.Client(api_key=GEMINI_KEY)

# Single-user demo state kept in memory in the pod
#STATE = {"chat": None, "tools": None, "pending": None}
STATE = {"chat": None, "tools": None, "pending": None,"prompt": None, "since_id": 0, "pending_row_id": None}


def mcp_tools_to_gemini(mcp_tools):
    decls = []
    for t in mcp_tools:
        schema = dict(t.input_schema or {})
        schema.pop("$schema", None)
        schema.pop("additionalProperties", None)
        decls.append(types.FunctionDeclaration(
            name=t.name, description=t.description or "", parameters=schema))
    return [types.Tool(function_declarations=decls)]

async def fetch_tools():
    async with streamable_http_client(MCP_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return (await session.list_tools()).tools

async def mcp_call(name, args):
    async with streamable_http_client(MCP_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(name, args)
            return result.content[0].text if result.content else ""

def new_chat():
    return gemini.chats.create(
        model=MODEL,
        config=types.GenerateContentConfig(tools=STATE["tools"]),
    )

def first_fc(response):
    for p in response.candidates[0].content.parts:
        if getattr(p, "function_call", None):
            return p.function_call
    return None

def safe_text(response):
    try:
        return response.text or ""
    except Exception:
        return "".join(getattr(p, "text", "") or "" for p in response.candidates[0].content.parts)

async def send(msg):
    # send_message is blocking → run off the event loop
    return await asyncio.to_thread(STATE["chat"].send_message, msg)

async def drive(response):
    """Run the tool loop until a final answer, or until a write needs approval."""
    fc = first_fc(response)
    while fc:
        args = dict(fc.args)
        # The EXECUTE phase of a write (token present) must get human approval
        if fc.name in WRITE_TOOLS and args.get("confirm_token"):
            STATE["pending"] = {"name": fc.name, "args": args}
            return {"type": "approval_required", "tool": fc.name, "args": args}
        out = await mcp_call(fc.name, args)
        response = await send([types.Part.from_function_response(
            name=fc.name, response={"result": out})])
        fc = first_fc(response)
    return {"type": "answer", "text": safe_text(response)}

@asynccontextmanager
async def lifespan(app):
    tools = await fetch_tools()
    STATE["tools"] = mcp_tools_to_gemini(tools)
    STATE["chat"]  = new_chat()
    yield

app = FastAPI(lifespan=lifespan)

class ChatIn(BaseModel):
    message: str

class ApproveIn(BaseModel):
    approved: bool

@app.post("/chat")
async def chat(inp: ChatIn):
    STATE["prompt"] = inp.message
    STATE["since_id"] = await asyncio.to_thread(max_id)
    response = await send(inp.message)
    result = await drive(response)
    if result["type"] == "approval_required":
        STATE["pending_row_id"] = await asyncio.to_thread(pending_id, result["tool"])
    await asyncio.to_thread(tag_prompt, STATE["since_id"], STATE["prompt"])
    return result

@app.post("/approve")
async def approve(inp: ApproveIn):
    pending = STATE.get("pending")
    if not pending:
        return {"type": "answer", "text": "Nothing was awaiting approval."}
    STATE["pending"] = None
    if inp.approved:
        out = await mcp_call(pending["name"], pending["args"])   # writes 'executed' row
        await asyncio.to_thread(delete_row, STATE["pending_row_id"])  # remove the pending row
    else:
        out = '{"status":"denied_by_human"}'
        await asyncio.to_thread(mark_declined, STATE["pending_row_id"])  # pending -> declined
    STATE["pending_row_id"] = None
    response = await send([types.Part.from_function_response(
        name=pending["name"], response={"result": out})])
    result = await drive(response)
    await asyncio.to_thread(tag_prompt, STATE["since_id"], STATE["prompt"])
    return result

@app.post("/reset")
async def reset():
    STATE["chat"] = new_chat()
    STATE["pending"] = None
    return {"type": "answer", "text": "Conversation reset."}

@app.get("/health")
def health():
    return {"ok": True, "model": MODEL}


import asyncio
import os
import random

from dotenv import load_dotenv
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

load_dotenv()

gemini = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MCP_URL = os.getenv("MCP_SERVER_URL")
WRITE_TOOLS = {"scale_gke_node_pool"}

RETRYABLE_CODES = {429, 500, 502, 503, 504}

def mcp_tools_to_gemini(mcp_tools):
    declarations = []

    for tool in mcp_tools:
        schema = dict(tool.input_schema or {})
        schema.pop("$schema", None)
        schema.pop("additionalProperties", None)

        declarations.append(
            types.FunctionDeclaration(
                name=tool.name,
                description=tool.description or "",
                parameters=schema,
            )
        )

    return [types.Tool(function_declarations=declarations)]

async def send_message_with_retry(chat, contents, attempts=5):
    for attempt in range(attempts):
        try:
            # chat.send_message() is synchronous
            return await asyncio.to_thread(
                chat.send_message,
                contents,
            )

        except genai_errors.APIError as exc:
            code = (
                getattr(exc, "code", None)
                or getattr(exc, "status_code", None)
            )

            if code not in RETRYABLE_CODES:
                raise

            if attempt == attempts - 1:
                raise

            delay = min(2**attempt, 16) + random.uniform(0, 1)
            print(
                f"Gemini returned {code}; "
                f"retrying in {delay:.1f} seconds..."
            )
            await asyncio.sleep(delay)

def get_function_call(response):
    for candidate in response.candidates or []:
        if not candidate.content:
            continue

        for part in candidate.content.parts or []:
            if part.function_call:
                return part.function_call

    return None

async def main():
    async with streamable_http_client(MCP_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tool_list = (await session.list_tools()).tools
            gemini_tools = mcp_tools_to_gemini(tool_list)

            print(f"Connected. Tools: {[tool.name for tool in tool_list]}\n")

            chat = gemini.chats.create(
                model="gemini-3.7-flash",
                config=types.GenerateContentConfig(
                    tools=gemini_tools
                ),
            )

            print("Ask about your infrastructure ('quit' to exit).")

            while True:
                user_input = input("\nYou: ")

                if user_input.strip().lower() in {"quit", "exit"}:
                    break

                try:
                    response = await send_message_with_retry(
                        chat,
                        user_input,
                    )

                    while True:
                        fc = get_function_call(response)

                        if not fc:
                            break

                        args = dict(fc.args or {})
                        print(f"[AI wants: {fc.name} args={args}]")

                        if fc.name in WRITE_TOOLS and args.get(
                            "confirm_token"
                        ):
                            approval = input(
                                f"⚠️ Approve EXECUTE {fc.name} "
                                f"{args}? (yes/no): "
                            )

                            if approval.strip().lower() != "yes":
                                out = '{"status":"denied_by_human"}'

                                response = (
                                    await send_message_with_retry(
                                        chat,
                                        [
                                            types.Part.from_function_response(
                                                name=fc.name,
                                                response={"result": out},
                                            )
                                        ],
                                    )
                                )
                                continue

                        result = await session.call_tool(
                            fc.name,
                            args,
                        )

                        out = "\n".join(
                            item.text
                            for item in result.content
                            if getattr(item, "text", None)
                        )

                        response = await send_message_with_retry(
                            chat,
                            [
                                types.Part.from_function_response(
                                    name=fc.name,
                                    response={"result": out},
                                )
                            ],
                        )

                    print(f"\nGemini: {response.text}")

                except genai_errors.APIError as exc:
                    print(f"\nGemini request failed temporarily: {exc}")
                    print("The MCP connection is still active; try again.")

                except Exception as exc:
                    print(f"\nRequest failed: {exc}")

if __name__ == "__main__":
    asyncio.run(main())


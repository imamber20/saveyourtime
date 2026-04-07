"""
Phase 4 — AI Chatbot Service
==============================
Provides two chat modes:

1. Per-item chat  — assistant has full context of a single saved item
                    (transcript, summary, key_points, visual_text, tags).
2. Library chat   — assistant searches across ALL the user's saved items
                    via pgvector semantic similarity before answering.

Both modes support:
  • Brave web search tool (for fact-checking / up-to-date info)
  • Streaming token output (async generator → FastAPI StreamingResponse)
"""

from __future__ import annotations

import os
import json
import logging
import httpx
from typing import AsyncGenerator, List, Dict, Optional, Any

logger = logging.getLogger("content_memory.chat")

BRAVE_API_KEY    = os.getenv("BRAVE_API_KEY", "")
BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"

# Number of library items to inject as context for global chat
LIBRARY_TOP_K = 8

# Maximum characters of transcript to include in per-item context
TRANSCRIPT_MAX_CHARS = 3000


# ─── Brave web search tool ───────────────────────────────────────────────────

async def brave_web_search(query: str, count: int = 3) -> str:
    """Call Brave Search API and return a formatted summary of the top results."""
    if not BRAVE_API_KEY:
        return "Web search unavailable (no API key configured)."

    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(
                BRAVE_SEARCH_URL,
                params={"q": query, "count": count, "text_decorations": False},
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "X-Subscription-Token": BRAVE_API_KEY,
                },
            )
        data = resp.json()
        results = data.get("web", {}).get("results", [])
        if not results:
            return f"No web results found for: {query}"

        lines = [f"Web search results for: {query}\n"]
        for i, r in enumerate(results[:count], 1):
            title = r.get("title", "")
            url   = r.get("url", "")
            desc  = r.get("description", "")
            lines.append(f"{i}. {title}\n   {url}\n   {desc}\n")
        return "\n".join(lines)

    except Exception as e:
        logger.warning(f"Brave search failed: {e}")
        return f"Web search error: {e}"


# ─── Tool definition (OpenAI function-calling format) ────────────────────────

WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the web using Brave Search to find current information, "
            "fact-check claims, or get details not in the saved content."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query",
                }
            },
            "required": ["query"],
        },
    },
}


# ─── Streaming helper ────────────────────────────────────────────────────────

async def _stream_with_tools(
    client,
    messages: List[Dict],
    system_prompt: str,
) -> AsyncGenerator[str, None]:
    """
    Run a GPT-4o-mini chat completion with the web_search tool.
    Yields SSE-formatted strings:
      data: {"type": "token", "content": "..."}
      data: {"type": "search_used", "query": "..."}
      data: {"type": "done"}
    """
    full_messages = [{"role": "system", "content": system_prompt}] + messages

    # ── First pass: may trigger tool calls ───────────────────────────────────
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=full_messages,
        tools=[WEB_SEARCH_TOOL],
        tool_choice="auto",
        temperature=0.4,
        stream=False,           # need full response to inspect tool calls
        max_tokens=1200,
    )

    choice = response.choices[0]
    msg    = choice.message

    # If the model wants to use the search tool, execute it then re-run
    if msg.tool_calls:
        tool_call = msg.tool_calls[0]
        args      = json.loads(tool_call.function.arguments)
        query     = args.get("query", "")

        yield f"data: {json.dumps({'type': 'search_used', 'query': query})}\n\n"
        search_result = await brave_web_search(query)

        # Append tool call + result to messages and re-run with streaming
        full_messages.append(msg)  # assistant message with tool_calls
        full_messages.append({
            "role":         "tool",
            "tool_call_id": tool_call.id,
            "content":      search_result,
        })

        stream = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=full_messages,
            temperature=0.4,
            stream=True,
            max_tokens=1200,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield f"data: {json.dumps({'type': 'token', 'content': delta.content})}\n\n"
    else:
        # No tool call — stream the response content token by token
        stream = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=full_messages,
            temperature=0.4,
            stream=True,
            max_tokens=1200,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield f"data: {json.dumps({'type': 'token', 'content': delta.content})}\n\n"

    yield f"data: {json.dumps({'type': 'done'})}\n\n"


# ─── Per-item chat ────────────────────────────────────────────────────────────

async def item_chat(
    item: Dict,
    messages: List[Dict],
) -> AsyncGenerator[str, None]:
    """
    Stream a chat response grounded in a single saved item's content.

    Args:
        item:     Full item dict from Supabase (title, summary, key_points, …)
        messages: Conversation history [{role, content}, …]
    """
    from services.ai_service import get_openai_client
    client = get_openai_client()
    if not client:
        async def _err():
            yield f"data: {json.dumps({'type': 'error', 'content': 'OpenAI API key not configured'})}\n\n"
        return _err()

    # Build rich context block from item fields
    ctx_lines: List[str] = [
        f"Title: {item.get('title', '')}",
        f"Platform: {item.get('platform', '')}",
        f"Category: {item.get('category', '')} / {item.get('sub_category', '')}",
        f"Tags: {', '.join(item.get('tags', []))}",
        f"Author: {item.get('author', '')}",
        f"Duration: {item.get('duration', '')}",
    ]

    if item.get("summary"):
        ctx_lines.append(f"\nSummary:\n{item['summary']}")

    if item.get("key_points"):
        ctx_lines.append("\nKey Points:\n" + "\n".join(f"• {kp}" for kp in item["key_points"]))

    if item.get("steps"):
        ctx_lines.append("\nSteps:\n" + "\n".join(f"{i+1}. {s}" for i, s in enumerate(item["steps"])))

    if item.get("ingredients"):
        ctx_lines.append("\nIngredients:\n" + "\n".join(f"• {ing}" for ing in item["ingredients"]))

    if item.get("visual_text"):
        ctx_lines.append(f"\nVisual Content Observed:\n{item['visual_text'][:500]}")

    if item.get("transcript_excerpt"):
        excerpt = item["transcript_excerpt"][:TRANSCRIPT_MAX_CHARS]
        ctx_lines.append(f"\nTranscript Excerpt:\n{excerpt}")

    if item.get("notes"):
        ctx_lines.append(f"\nUser Notes:\n{item['notes']}")

    item_context = "\n".join(ctx_lines)

    system_prompt = f"""You are a helpful assistant answering questions about a saved piece of content.

Here is everything known about the content:
---
{item_context}
---

Answer questions about this content. You can use the web_search tool to fact-check claims,
find more details about places mentioned, or get up-to-date information.
Be concise and direct. If the content doesn't cover something, say so."""

    return _stream_with_tools(client, messages, system_prompt)


# ─── Global library chat ──────────────────────────────────────────────────────

async def library_chat(
    messages: List[Dict],
    user_id: str,
    supabase_client,
) -> AsyncGenerator[str, None]:
    """
    Stream a chat response using semantic search across the user's entire library.

    Args:
        messages:         Conversation history.
        user_id:          Supabase auth UUID of the user.
        supabase_client:  Initialised AsyncClient (from server.py global).
    """
    from services.ai_service import get_openai_client, generate_embedding
    client = get_openai_client()
    if not client:
        async def _err():
            yield f"data: {json.dumps({'type': 'error', 'content': 'OpenAI API key not configured'})}\n\n"
        return _err()

    # Use the last user message as the embedding query
    user_message = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            user_message = m.get("content", "")
            break

    # ── Vector search for relevant items ─────────────────────────────────────
    context_block = ""
    try:
        query_embedding = await generate_embedding(user_message)
        if query_embedding:
            # pgvector cosine distance — requires the match_items RPC or direct SQL
            # We use the RPC function approach (defined in Supabase)
            try:
                rpc_res = await supabase_client.rpc(
                    "match_items",
                    {
                        "query_embedding": query_embedding,
                        "match_user_id":   user_id,
                        "match_count":     LIBRARY_TOP_K,
                    }
                ).execute()
                top_items = rpc_res.data or []
            except Exception:
                # Fallback: fetch recent completed items if RPC not set up yet
                fallback_res = await supabase_client.table("items") \
                    .select("id, title, summary, category, tags, key_points") \
                    .eq("user_id", user_id) \
                    .eq("source_status", "completed") \
                    .order("created_at", desc=True) \
                    .limit(LIBRARY_TOP_K) \
                    .execute()
                top_items = fallback_res.data or []

            if top_items:
                item_summaries = []
                for it in top_items:
                    tags    = it.get("tags") or []
                    kp      = it.get("key_points") or []
                    summary = it.get("summary", "")[:200]
                    item_summaries.append(
                        f"• [{it.get('category', 'Unknown')}] {it.get('title', 'Untitled')}"
                        f"{' — ' + summary if summary else ''}"
                        f"{' Tags: ' + ', '.join(tags[:5]) if tags else ''}"
                        f"{chr(10) + '  Key points: ' + '; '.join(kp[:3]) if kp else ''}"
                    )
                context_block = "Relevant items from your library:\n" + "\n".join(item_summaries)

    except Exception as e:
        logger.warning(f"Library vector search failed: {e}")

    system_prompt = f"""You are a helpful assistant that knows the user's saved content library.

{context_block if context_block else 'No specific items were retrieved for this query.'}

Answer questions about the user's saved content.
You can use the web_search tool to supplement with current information.
Be conversational, reference specific saved items by name when relevant.
If you're not sure whether the user has saved something, say so."""

    return _stream_with_tools(client, messages, system_prompt)

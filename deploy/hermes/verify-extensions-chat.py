"""Verify the real HTTPS WebUI -> selected model -> Hermes extension tool loop.

Uses the administrator account only in server memory. If it has no personal
DeepSeek key, temporarily validates the existing server key and removes that
temporary entry in finally. Does not overwrite an existing personal key.
"""
import json
from pathlib import Path
import sqlite3
import time
import uuid

ROOT = Path("/home/ubuntu/haudi-hermes")
EXPECTED = {"skill_view", "research_citation", "mcp__research_papers__crossref_search",
            "mcp__research_papers__crossref_lookup", "mcp__research_papers__europepmc_search",
            "mcp__research_papers__europepmc_fulltext"}


def decode_tool_result(content):
    # The agent persists external results inside an untrusted-data boundary.
    if content.startswith('<untrusted_tool_result source="'):
        content = content.split("\n\n", 1)[1].rsplit("\n</untrusted_tool_result>", 1)[0]
    return json.loads(content)


def verify_recorded_calls(marker):
    with sqlite3.connect(ROOT / "state/state.db") as db:
        row = db.execute("SELECT s.id,s.model FROM sessions s JOIN messages m ON m.session_id=s.id "
                         "WHERE m.role='user' AND m.content LIKE ? ORDER BY m.timestamp DESC LIMIT 1", ("%" + marker + "%",)).fetchone()
        assert row and row[1] == "deepseek-v4-flash", "Selected runtime model mismatch"
        rows = db.execute("SELECT tool_name,content FROM messages WHERE session_id=? AND role='tool'", (row[0],)).fetchall()
    observed = {name for name, _ in rows if name}
    assert EXPECTED <= observed, "Missing actual tool calls: " + ", ".join(sorted(EXPECTED - observed))
    for name, content in rows:
        if name in EXPECTED:
            value = decode_tool_result(content)
            assert not value.get("error") and not value.get("isError"), "Extension tool returned error: " + name
    return {"status": "pass", "transport": "HTTPS", "model": row[1], "observed_tools": sorted(observed)}


def main():
    import httpx
    from dotenv import dotenv_values
    account = json.loads((ROOT / "openwebui/access.json").read_text())
    marker = "extension-check-" + uuid.uuid4().hex
    prompt = marker + """ 这是科研扩展验收任务，请实际调用工具，不使用终端或代码代替：
先用 skill_view 加载 research-literature。
用 mcp__research_papers__crossref_search 搜索 CRISPR（limit=1），再用 crossref_lookup 工具核对返回 DOI。
用 mcp__research_papers__europepmc_search 搜索 CRISPR OPEN_ACCESS:Y（limit=1），用 europepmc_fulltext 工具按返回 PMCID 读取正文（max_chars=1000）。
最后用 research_citation 工具排版 Crossref 返回的真实论文，year 如提供则转换为四位字符串。
如果工具被延迟展示，先使用 tool_search 查找。回答简短给出两个来源链接和证据层级。
"""
    added = False
    start = time.monotonic()
    with httpx.Client(base_url="https://42.193.15.167", timeout=600, trust_env=False) as client:
        login = client.post("/api/v1/auths/signin", json={k: account[k] for k in ("email", "password")})
        assert login.status_code == 200, "Administrator sign-in failed"
        client.headers["Authorization"] = "Bearer " + login.json()["token"]
        result = client.get("/api/workstation/catalog")
        assert result.status_code == 200
        configured = result.json()["credentials"]["deepseek"]["configured"]
        try:
            if not configured:
                env = dotenv_values(ROOT / "state/.env")
                key = env.get("DEEPSEEK_API_KEY") or env.get("OPENAI_API_KEY")
                assert key, "No existing test provider key"
                result = client.post("/api/workstation/credentials", json={"model_id": "ws-deepseek-v4-flash",
                                     "endpoint_id": "official", "api_key": key})
                assert result.status_code == 200, "Temporary test key validation failed"
                added = True
            parts = []
            with client.stream("POST", "/api/chat/completions", json={"model": "ws-deepseek-v4-flash",
                               "stream": True, "messages": [{"role": "user", "content": prompt}]}) as response:
                assert response.status_code == 200, f"Chat HTTP {response.status_code}"
                for line in response.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw or raw == "[DONE]":
                        continue
                    event = json.loads(raw)
                    assert not event.get("error"), "Model stream returned an error"
                    for choice in event.get("choices", []):
                        text = choice.get("delta", {}).get("content")
                        if isinstance(text, str):
                            parts.append(text)
            assert parts, "No streaming reply"
            report = {**verify_recorded_calls(marker), "elapsed_seconds": round(time.monotonic() - start, 1),
                      "temporary_key_used": added}
            (ROOT / "extensions/chat-verification.json").write_text(json.dumps(report, indent=2))
            print(json.dumps(report), flush=True)
        finally:
            if added:
                response = client.delete("/api/workstation/credentials/deepseek")
                assert response.status_code == 200, "Temporary administrator key cleanup failed"
                print("Temporary administrator key removed.", flush=True)


if __name__ == "__main__":
    main()

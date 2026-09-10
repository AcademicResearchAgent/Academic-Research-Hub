"""Relay Agent SSE with native WebUI status events, preserving reasoning deltas."""
import asyncio
from contextlib import suppress
import json
import time


def frame(data):
    return ("data: " + json.dumps(data, ensure_ascii=False) + "\n\n").encode()


def status(description, done=False, **extra):
    return frame({"event": {"type": "status", "data": {"description": description, "done": done, **extra}}})


async def stream_agent_response(client, request, heartbeat_seconds=10, public_filter=None):
    """First feedback precedes upstream headers; silence never fabricates reasoning.

    Keep a single pending read across heartbeat ticks: wait_for would cancel the
    upstream iterator and lose/abort the response. Closing the generator cancels
    that pending operation and closes the HTTP stream as well.
    """
    started = last_status = time.monotonic()
    phase = "正在连接科研助手"
    response = pending = None
    tools = {}
    failed = False
    try:
        yield status(phase)
        pending = asyncio.create_task(client.send(request, stream=True))
        while not pending.done():
            completed, _ = await asyncio.wait({pending}, timeout=heartbeat_seconds)
            if not completed:
                last_status = time.monotonic()
                yield status(f"{phase}，已用时 {int(last_status - started)} 秒")
        response = await pending
        pending = None
        if response.status_code != 200:
            yield status("模型调用失败", done=True)
            yield frame({"error": {"message": "所选模型调用失败，请检查 API Key、余额或模型权限。"}})
            yield b"data: [DONE]\n\n"
            return
        phase = "正在处理研究任务"
        yield status(phase)
        lines = response.aiter_lines().__aiter__()
        event_name, data_lines = "", []
        while True:
            if pending is None:
                pending = asyncio.create_task(anext(lines))
            timeout = max(0, heartbeat_seconds - (time.monotonic() - last_status))
            completed, _ = await asyncio.wait({pending}, timeout=timeout)
            if not completed:
                last_status = time.monotonic()
                yield status(f"{phase}，已用时 {int(last_status - started)} 秒")
                continue
            try:
                line = pending.result()
            except StopAsyncIteration:
                pending = None
                raise RuntimeError("Agent stream ended before DONE")
            pending = None
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip(" "))
            elif not line:
                if not data_lines:
                    event_name = ""
                    continue
                raw = "\n".join(data_lines)
                data_lines = []
                if raw == "[DONE]":
                    if public_filter:
                        remaining = public_filter.flush()
                        if remaining:
                            yield frame(remaining)
                    for call_id, activity in tools.items():
                        yield status(activity["title"], action="workstation_tool", toolCallId=call_id,
                                     activity={**activity, "state": "interrupted", "summary": "本轮已结束，未收到工具完成回执"})
                    yield status("本次生成未完成" if failed else "本次生成已结束", done=True)
                    yield b"data: [DONE]\n\n"
                    return
                data = json.loads(raw)
                if public_filter:
                    from open_webui.workstation_workspace.public_paths import clean_object
                    data = public_filter.transform(data) if data.get('choices') else clean_object(data)
                if event_name == "workstation.status":
                    phase = str(data.get("description", "正在处理项目文件"))
                    yield status(phase)
                    last_status = time.monotonic()
                elif event_name == "workstation.files":
                    from open_webui.workstation_workspace.public_stream import public_files
                    files = public_files(data)
                    if files:
                        yield frame({"event": {"type": "files", "data": {"files": files}}})
                    if data.get("conflicts"):
                        yield status("文件存在并发修改，已保留 Agent 冲突副本", done=True)
                    if data.get("skipped"):
                        yield status("部分特殊文件未发布，请在项目中检查产物", done=True)
                    if data.get("recovery_available"):
                        failed = True
                        yield status("本次运行未完成，输出已保留；可在项目菜单的“未完成文件”中恢复，原文件未被覆盖。", done=True)
                elif event_name == "hermes.tool.progress":
                    call_id = data.get("toolCallId")
                    activity = data.get("activity")
                    if not isinstance(activity, dict):
                        activity = {"title": "工具：" + str(data.get("tool", "未命名工具"))[:100],
                                    "state": "running" if data.get("status") == "running" else "completed",
                                    "summary": "此工具未提供详细运行信息"}
                    if data.get("status") == "running" and call_id:
                        tools[call_id] = activity
                    elif call_id:
                        tools.pop(call_id, None)
                    phase = activity.get("title", "工具调用") + " · " + (activity.get("summary") or activity.get("detail") or "执行中")
                    yield status(phase, action="workstation_tool", toolCallId=call_id, activity=activity)
                    last_status = time.monotonic()
                else:
                    # Preserve all model deltas and usage fields; no vendor-specific rendering.
                    next_phase = phase
                    for choice in data.get("choices", []):
                        delta = choice.get("delta", {})
                        if delta.get("reasoning_content") or delta.get("reasoning") or delta.get("thinking"):
                            next_phase = "正在思考"
                        elif delta.get("content"):
                            next_phase = "正在生成回答"
                        if choice.get("finish_reason") in {"error", "length", "content_filter"}:
                            failed = True
                    if data.get("error"):
                        failed = True
                        next_phase = "生成遇到错误"
                    if next_phase != phase:
                        phase = next_phase
                        yield status(phase)
                        last_status = time.monotonic()
                    yield frame(data)
                event_name = ""
    except (asyncio.CancelledError, GeneratorExit):
        raise
    except Exception:
        for call_id, activity in tools.items():
            yield status(activity["title"], action="workstation_tool", toolCallId=call_id,
                         activity={**activity, "state": "interrupted", "summary": "连接中断，未收到工具完成回执"})
        yield status("连接中断，请重试", done=True)
        yield frame({"error": {"message": "科研助手流式连接中断，请重试。"}})
        yield b"data: [DONE]\n\n"
    finally:
        if pending is not None:
            pending.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await pending
        if response is not None:
            await response.aclose()
        await client.aclose()

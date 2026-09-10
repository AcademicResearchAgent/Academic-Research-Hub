"""Authenticated workspace API; native chat ownership is checked at the bridge."""
import asyncio
import os
from pathlib import Path
from weakref import WeakValueDictionary
from urllib.parse import quote
from uuid import uuid4, uuid5, UUID, NAMESPACE_URL

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field
from sqlalchemy import select

from open_webui.internal.db import get_async_db_context
from open_webui.models.chats import Chat, ChatForm, Chats
from open_webui.models.files import Files
from open_webui.utils.auth import get_verified_user
from .store import WorkspaceStore, WorkspaceError
from .migration import owned_upload_bytes
from .runs import recoverable_runs, recover_run
from .drafts import has_messages, first_title, promote


class WorkspaceRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def guarded(request):
            try:
                return await handler(request)
            except WorkspaceError as error:
                return JSONResponse({'detail': str(error)}, status_code=error.status)
        return guarded


router = APIRouter(route_class=WorkspaceRoute)
_store = None


def store():
    global _store
    if _store is None:
        root = os.environ.get('WORKSTATION_WORKSPACE_ROOT')
        if not root:
            raise HTTPException(503, '文件工作区尚未配置。')
        _store = WorkspaceStore(root)
    return _store


def public_node(node):
    return {k: v for k, v in node.items() if k in {
        'id', 'project', 'parent', 'name', 'path', 'kind', 'version', 'size',
        'mime', 'source', 'thread', 'run', 'created', 'updated', 'deleted'}}


def check_destination(user_id, project_id, parent=None):
    # Even a permission-only transaction can wait for SQLite's write lock.
    # Call this through to_thread so unrelated sign-out/health requests remain
    # responsive while another workspace operation is committing.
    with store().db() as db:
        if parent is None:
            store()._project(db, user_id, project_id)
        else:
            store()._parent(db, user_id, project_id, parent)


async def own_chat(user_id, chat_id):
    if not isinstance(chat_id, str) or not chat_id or len(chat_id) > 200:
        raise HTTPException(400, '请先创建当前项目的对话。')
    chat = await Chats.get_chat_by_id_and_user_id(chat_id, user_id)
    if chat is None:
        raise HTTPException(404, '对话不存在或无权访问。')
    if (chat.meta or {}).get('workspace_pending'):
        raise HTTPException(409, '正在保存首次输入，请稍后重试。')
    return chat


async def bind_chat(user_id, chat_id):
    chat = await own_chat(user_id, chat_id)
    return await asyncio.to_thread(store().ensure_thread, user_id, chat.id, chat.title)


async def import_native_file(user_id, project_id, file_id, thread=None):
    file = await Files.get_file_by_id_and_user_id(file_id, user_id)
    if not file or not file.path:
        raise HTTPException(404, '附件不存在或无权访问。')
    # Only native storage metadata obtained after owner validation selects the
    # source path. Never consume a path supplied in chat JSON or by the model.
    from open_webui.storage.provider import Storage
    from open_webui.config import UPLOAD_DIR
    path = await asyncio.to_thread(Storage.get_file, file.path)
    try:
        data = await asyncio.to_thread(owned_upload_bytes, path, UPLOAD_DIR, store().max_file_bytes)
    except OSError:
        raise HTTPException(404, '附件原文件不可用。') from None
    return await asyncio.to_thread(store().create_node, user_id, project_id, file.filename,
                                   content=data, source='upload', thread=thread, source_id='webui:' + file.id)


@router.get('/projects')
async def projects(user=Depends(get_verified_user)):
    # Idempotently adopt existing native chats. No shared filesystem is scanned.
    async with get_async_db_context() as db:
        rows = (await db.execute(select(Chat.id, Chat.title, Chat.meta, Chat.chat).where(Chat.user_id == user.id))).all()
    meaningful = set()
    for row in rows:
        if isinstance(row.meta, dict) and row.meta.get('internal'):
            continue
        if has_messages(row.chat or {}):
            meaningful.add(row.id)
        try:
            await asyncio.to_thread(store().ensure_thread, user.id, row.id, row.title)
        except WorkspaceError as error:
            if error.status != 404:  # Deleted projects/threads stay deleted.
                raise
    def visible_projects():
        result = store().projects(user.id)
        with store().db() as db:
            populated = {row[0] for row in db.execute('SELECT DISTINCT project FROM nodes WHERE deleted=0')}
        return [project for project in result if project['id'] in populated or
                any(thread['id'] in meaningful for thread in project['threads'])]
    return await asyncio.to_thread(visible_projects)


class DraftForm(BaseModel):
    project: str | None = None
    chat: dict = Field(default_factory=dict)
    file_ids: list[str] = Field(default_factory=list, max_length=100)


_draft_locks = WeakValueDictionary()


@router.post('/drafts/{draft}/commit')
async def commit_draft(draft: UUID, form: DraftForm, user=Depends(get_verified_user)):
    # Owner participates in the deterministic ID; another account cannot reuse
    # a draft token to address this account's chat. Retries return the same work.
    thread = str(uuid5(NAMESPACE_URL, 'workstation-draft:' + user.id + ':' + str(draft)))
    lock = _draft_locks.setdefault(thread, asyncio.Lock())
    async with lock:
        existing = await Chats.get_chat_by_id_and_user_id(thread, user.id)
        if existing and not (existing.meta or {}).get('workspace_pending'):
            project = await asyncio.to_thread(store().project_for_thread, user.id, thread)
            if form.project and form.project != project['id']:
                raise HTTPException(409, '草稿已经属于另一个项目。')
            return {'project': project, 'thread': thread}
        if form.project:
            await asyncio.to_thread(check_destination, user.id, form.project)
        attachments = []
        from open_webui.storage.provider import Storage
        from open_webui.config import UPLOAD_DIR
        for file_id in dict.fromkeys(form.file_ids):
            file = await Files.get_file_by_id_and_user_id(file_id, user.id)
            if not file or not file.path:
                raise HTTPException(404, '附件不存在或无权访问。')
            path = await asyncio.to_thread(Storage.get_file, file.path)
            content = await asyncio.to_thread(owned_upload_bytes, path, UPLOAD_DIR, store().max_file_bytes)
            attachments.append({'id': file.id, 'name': file.filename, 'content': content})
        title = first_title(form.chat, attachments)
        document = {k: v for k, v in form.chat.items() if k in ('models', 'history', 'messages', 'params', 'timestamp')}
        document.setdefault('history', {'messages': {}, 'currentId': None})
        document.setdefault('messages', [])
        document['title'] = title
        document['files'] = [{'id': file['id'], 'name': file['name'], 'type': 'file', 'status': 'uploaded',
                              'url': '/api/v1/files/' + file['id'] + '/content'} for file in attachments]
        if not existing:
            existing = await Chats.insert_new_chat(thread, user.id, ChatForm(chat=document),
                        internal_meta={'internal': True, 'workspace_pending': True})
            if existing is None:
                raise HTTPException(500, '保存首次输入失败，请重试。')
        try:
            project = await asyncio.to_thread(promote, store(), user.id, thread, title, form.project, attachments)
        except Exception:
            await Chats.delete_chat_by_id(thread)
            raise
        # Make the fully materialized chat visible to native and workspace lists.
        async with get_async_db_context() as db:
            from sqlalchemy import update
            await db.execute(update(Chat).where(Chat.id == thread, Chat.user_id == user.id).values(meta={}))
            await db.commit()
        return {'project': project, 'thread': thread}


class NewThread(BaseModel):
    project: str | None = None
    title: str = Field(default='新项目', min_length=1, max_length=200)


@router.post('/projects')
async def create_project(form: NewThread, user=Depends(get_verified_user)):
    if form.project:
        await asyncio.to_thread(check_destination, user.id, form.project)
    chat_id = str(uuid4())
    chat = await Chats.insert_new_chat(chat_id, user.id, ChatForm(chat={
        'title': form.title, 'models': [], 'history': {'messages': {}, 'currentId': None}, 'messages': []}))
    if chat is None:
        raise HTTPException(500, '创建对话失败。')
    try:
        project = await asyncio.to_thread(store().ensure_thread, user.id, chat.id, form.title, form.project)
    except Exception:
        # The new chat contains no messages; compensate an incomplete creation.
        await Chats.delete_chat_by_id(chat.id)
        raise
    return {'project': project, 'thread': chat.id}


@router.get('/threads/{thread}/workspace')
async def thread_workspace(thread: str, user=Depends(get_verified_user)):
    await bind_chat(user.id, thread)
    return await asyncio.to_thread(store().project_for_thread, user.id, thread)


@router.post('/threads/{thread}/open')
async def open_thread(thread: str, user=Depends(get_verified_user)):
    await bind_chat(user.id, thread)
    return await asyncio.to_thread(store().project_for_thread, user.id, thread, remember=True)


class TitleForm(BaseModel):
    title: str = Field(min_length=1, max_length=200)


@router.get('/projects/{project}/recoverable-runs')
async def list_recoverable_runs(project: str, user=Depends(get_verified_user)):
    return await asyncio.to_thread(recoverable_runs, store(), user.id, project)


@router.post('/projects/{project}/recoverable-runs/{run}/recover')
async def restore_run_files(project: str, run: str, user=Depends(get_verified_user)):
    result = await asyncio.to_thread(recover_run, store(), user.id, project, run)
    return {**result, 'files': [public_node(file) for file in result['files']]}


@router.patch('/projects/{project}')
async def rename_project(project: str, form: TitleForm, user=Depends(get_verified_user)):
    await asyncio.to_thread(store().rename_project, user.id, project, form.title)
    return {'ok': True}


@router.delete('/projects/{project}')
async def delete_project(project: str, user=Depends(get_verified_user)):
    await asyncio.to_thread(store().delete_project, user.id, project)
    return {'deleted': True, 'recoverable': True}


@router.get('/projects-trash')
async def project_trash(user=Depends(get_verified_user)):
    return await asyncio.to_thread(store().projects, user.id, deleted=True)


@router.post('/projects/{project}/restore')
async def restore_project(project: str, user=Depends(get_verified_user)):
    await asyncio.to_thread(store().delete_project, user.id, project, restore=True)
    return {'restored': True}


@router.delete('/threads/{thread}')
async def delete_thread(thread: str, user=Depends(get_verified_user)):
    await own_chat(user.id, thread)
    await asyncio.to_thread(store().delete_thread, user.id, thread)
    # Retain native messages for recovery, hidden from the workspace navigation.
    return {'deleted': True, 'files_preserved': True}


@router.patch('/threads/{thread}')
async def rename_thread(thread: str, form: TitleForm, user=Depends(get_verified_user)):
    chat = await own_chat(user.id, thread)
    await Chats.update_chat_by_id(thread, {'title': form.title})
    await asyncio.to_thread(store().ensure_thread, user.id, thread, form.title)
    return {'ok': True}


@router.get('/projects/{project}/files')
async def files(project: str, user=Depends(get_verified_user)):
    return [public_node(n) for n in await asyncio.to_thread(store().nodes, user.id, project)]


class NodeForm(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    parent: str = ''
    directory: bool = False
    content: str = Field(default='', max_length=2 * 1024 * 1024)


@router.post('/projects/{project}/files')
async def create_file(project: str, form: NodeForm, user=Depends(get_verified_user)):
    result = await asyncio.to_thread(store().create_node, user.id, project, form.name,
        parent=form.parent, directory=form.directory, content=form.content.encode('utf-8'), source='user')
    return public_node(result)


@router.post('/projects/{project}/upload')
async def upload(project: str, file: UploadFile = File(...), parent: str = Form(''), user=Depends(get_verified_user)):
    await asyncio.to_thread(check_destination, user.id, project, parent)
    try:
        content = await file.read(store().max_file_bytes + 1)
        if len(content) > store().max_file_bytes:
            raise HTTPException(413, '文件超过当前工作区大小限制。')
        return public_node(await asyncio.to_thread(store().create_node, user.id, project,
                           file.filename or '未命名文件', parent=parent, content=content, source='upload'))
    finally:
        await file.close()


class ImportForm(BaseModel):
    file_id: str
    thread: str | None = None


@router.post('/projects/{project}/import')
async def import_file(project: str, form: ImportForm, user=Depends(get_verified_user)):
    return public_node(await import_native_file(user.id, project, form.file_id, form.thread))


@router.get('/files/{node}/content')
async def content(node: str, revision: int | None = None, user=Depends(get_verified_user)):
    item, data = await asyncio.to_thread(store().read, user.id, node, revision)
    return Response(data, media_type=item['mime'], headers={
        'Content-Disposition': "attachment; filename*=UTF-8''" + quote(item['name'], safe=''),
        'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'private, no-store',
        'Content-Security-Policy': "sandbox; default-src 'none'", 'X-File-Version': str(item['version'])})


class EditForm(BaseModel):
    content: str = Field(max_length=2 * 1024 * 1024)
    version: int = Field(ge=1)


@router.put('/files/{node}/content')
async def edit(node: str, form: EditForm, user=Depends(get_verified_user)):
    return public_node(await asyncio.to_thread(store().edit, user.id, node, form.content.encode('utf-8'), form.version))


@router.get('/files/{node}/versions')
async def versions(node: str, user=Depends(get_verified_user)):
    return await asyncio.to_thread(store().versions, user.id, node)


class MoveForm(BaseModel):
    name: str
    parent: str = ''


@router.patch('/files/{node}')
async def move(node: str, form: MoveForm, user=Depends(get_verified_user)):
    await asyncio.to_thread(store().move, user.id, node, name=form.name, parent=form.parent)
    return {'ok': True}


@router.delete('/files/{node}')
async def delete_file(node: str, user=Depends(get_verified_user)):
    await asyncio.to_thread(store().delete_node, user.id, node)
    return {'deleted': True}


@router.post('/files/{node}/extract')
async def extract(node: str, user=Depends(get_verified_user)):
    return public_node(await asyncio.to_thread(store().extract_zip, user.id, node))

"""Materialize a single owned workspace; reconcile verified, stopped run outputs.

Snapshots use immutable versions. An editor may continue saving while the agent
works; reconciliation preserves both sides of a conflict instead of overwriting.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import time

from .store import WorkspaceError, identifier, valid_name


IGNORED_DIRS = {'.git', '__pycache__', 'node_modules', '.venv', '.cache'}


def begin_run(store, owner, thread):
    project = store.project_for_thread(owner, thread)['id']
    run_id, now = identifier(), time.time_ns()
    work = store.root / 'runs' / run_id / 'workspace'
    with store.db() as db:
        store._project(db, owner, project)
        if not db.execute('SELECT 1 FROM threads WHERE id=? AND deleted=0', (thread,)).fetchone():
            raise WorkspaceError('对话已删除。', 404)
        entries = store._paths(db.execute('SELECT * FROM nodes WHERE project=? AND deleted=0', (project,)).fetchall())
        base = {n['path']: n for n in entries}
        try:
            db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?)', (run_id, project, thread, 'running', json.dumps(base, ensure_ascii=False), now, now))
        except sqlite3.IntegrityError:
            raise WorkspaceError('此项目已有任务正在运行，请等待完成或停止后重试。', 409) from None
        work.mkdir(parents=True)
        for entry in sorted(entries, key=lambda n: (n['path'].count('/'), n['path'])):
            target = work.joinpath(*entry['path'].split('/'))
            if entry['kind'] == 'directory':
                target.mkdir(exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                data = (store.blobs / entry['id'] / str(entry['version'])).read_bytes()
                digest = hashlib.sha256(data).hexdigest()
                expected = db.execute('SELECT digest FROM versions WHERE node=? AND revision=?', (entry['id'], entry['version'])).fetchone()['digest']
                if digest != expected:
                    raise WorkspaceError('工作区文件完整性检查失败。', 500)
                target.write_bytes(data)
                base[entry['path']]['digest'] = digest
        db.execute('UPDATE runs SET base=? WHERE id=?', (json.dumps(base, ensure_ascii=False), run_id))
    return {'id': run_id, 'project': project, 'thread': thread, 'workspace': str(work)}


def inspect_outputs(directory, *, max_file_bytes, max_workspace_bytes, max_nodes):
    """Never follow symlinks, pipes or hardlinks. Broker stops the container first.

    Linux uses directory descriptors with O_NOFOLLOW for every path component,
    so a tree controlled by an agent cannot redirect host reads. Windows fallback
    is for local tests only; production execution requires Linux containers.
    """
    files, directories, skipped = {}, [], []
    total = 0

    def accept(name, relative):
        try:
            valid_name(name)
        except WorkspaceError:
            skipped.append(relative)
            return False
        if len(files) + len(directories) >= max_nodes:
            raise WorkspaceError('生成文件数量超过限制。', 413)
        return True

    def read_file(fd, relative):
        nonlocal total
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            skipped.append(relative)
            return
        if before.st_size > max_file_bytes or total + before.st_size > max_workspace_bytes:
            raise WorkspaceError('生成文件体积超过限制。', 413)
        with os.fdopen(os.dup(fd), 'rb') as source:
            content = source.read(max_file_bytes + 1)
        after = os.fstat(fd)
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise WorkspaceError('文件仍在写入，暂不能发布。', 409)
        if len(content) > max_file_bytes or total + len(content) > max_workspace_bytes:
            raise WorkspaceError('生成文件体积超过限制。', 413)
        total += len(content)
        files[relative] = content

    def linux_walk(fd, prefix=''):
        with os.scandir(fd) as entries:
            for entry in entries:
                rel = prefix + entry.name
                if entry.name in IGNORED_DIRS or not accept(entry.name, rel):
                    continue
                mode = entry.stat(follow_symlinks=False).st_mode
                if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                    skipped.append(rel)
                    continue
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                if stat.S_ISDIR(mode):
                    flags |= os.O_DIRECTORY
                child = os.open(entry.name, flags, dir_fd=fd)
                try:
                    if stat.S_ISDIR(mode):
                        directories.append(rel)
                        linux_walk(child, rel + '/')
                    else:
                        read_file(child, rel)
                finally:
                    os.close(child)

    if os.name == 'posix':
        root_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            linux_walk(root_fd)
        finally:
            os.close(root_fd)
    else:
        root = Path(directory).resolve()
        for current, dirs, names in os.walk(root, followlinks=False):
            dirs[:] = [n for n in dirs if n not in IGNORED_DIRS and not (Path(current) / n).is_symlink()]
            for name in dirs + names:
                path = Path(current) / name
                rel = path.relative_to(root).as_posix()
                if not accept(name, rel):
                    continue
                if path.is_symlink() or not path.resolve().is_relative_to(root):
                    skipped.append(rel)
                    continue
                if path.is_dir():
                    directories.append(rel)
                else:
                    with path.open('rb') as f:
                        read_file(f.fileno(), rel)
    return files, directories, skipped


def finish_run(store, owner, run_id, *, interrupted=False):
    """Called only after the execution container is confirmed stopped/absent."""
    with store.db() as db:
        run = db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
        if not run:
            raise WorkspaceError('运行不存在。', 404)
        store._project(db, owner, run['project'])
        if run['status'] != 'running':
            return {'files': [], 'conflicts': [], 'status': run['status']}
        if interrupted:
            # The process may have stopped halfway through a rewrite. Retain
            # the private copy without publishing or overwriting any live file.
            db.execute("UPDATE runs SET status='interrupted',updated=? WHERE id=?", (time.time_ns(), run_id))
            return {'files': [], 'conflicts': [], 'status': 'interrupted', 'recovery_available': True}
        run = dict(run)
    work = store.root / 'runs' / run_id / 'workspace'
    files, directories, skipped = inspect_outputs(work, max_file_bytes=store.max_file_bytes,
        max_workspace_bytes=store.max_workspace_bytes, max_nodes=store.max_nodes)
    # Publish the whole result and release its lease together. A quota failure
    # or process crash must not leave some new files registered and retry them
    # as duplicate/conflict copies on recovery.
    with store.db() as db:
        store._project(db, owner, run['project'])
        latest = db.execute('SELECT status FROM runs WHERE id=?', (run_id,)).fetchone()
        if latest['status'] != 'running':
            return {'files': [], 'conflicts': [], 'status': latest['status']}
        return _reconcile(store, owner, run, files, directories, skipped, interrupted)


def _reconcile(store, owner, run, files, directories, skipped, interrupted):
    run_id = run['id']
    base = json.loads(run['base'])
    current = {n['path']: n for n in store.nodes(owner, run['project'])}
    directories_by_path = {'': ''}
    for path, item in current.items():
        if item['kind'] == 'directory':
            directories_by_path[path] = item['id']
    changed, conflicts = [], []

    def parent_for(path):
        prefix = ''
        parent = ''
        for name in path.split('/')[:-1]:
            prefix = prefix + '/' + name if prefix else name
            if prefix not in directories_by_path:
                item = store.create_node(owner, run['project'], name, parent=parent, directory=True, source='agent', thread=run['thread'], run=run_id)
                directories_by_path[prefix] = item['id']
            parent = directories_by_path[prefix]
        return parent

    for directory in sorted(directories, key=lambda p: p.count('/')):
        parent_for(directory + '/placeholder')
    for path, content in files.items():
        original = base.get(path)
        digest = hashlib.sha256(content).hexdigest()
        if original and original.get('digest') == digest:
            continue
        if original and original['kind'] == 'file':
            try:
                item = store.edit(owner, original['id'], content, original['version'],
                                  source='agent', thread=run['thread'], run=run_id)
                changed.append(item)
                continue
            except WorkspaceError as error:
                if error.status not in {404, 409}:
                    raise
                # Deleted or concurrently edited: preserve the agent's output as
                # a new conflict file, never resurrect/overwrite the user's item.
                name = Path(path).name
                stem, suffix = os.path.splitext(name)
                name = valid_name(stem[:140] + '（Agent 冲突副本）' + suffix[:30])
                item = store.create_node(owner, run['project'], name, parent=parent_for(path), content=content, source='agent-conflict', thread=run['thread'], run=run_id)
                conflicts.append(item['id'])
                changed.append(item)
        else:
            item = store.create_node(owner, run['project'], path.split('/')[-1], parent=parent_for(path), content=content, source='agent', thread=run['thread'], run=run_id)
            changed.append(item)
    # Agent-side deletions are applied only if the user's version is unchanged.
    # On interruption preserve all pre-existing files (a tool may be mid-rewrite).
    if not interrupted:
        for path, original in base.items():
            if (original['kind'] == 'file' and path not in files
                    and not any(part in IGNORED_DIRS for part in path.split('/'))
                    and not any(path == p or path.startswith(p + '/') for p in skipped)):
                with store.db() as db:
                    item = db.execute('SELECT * FROM nodes WHERE id=? AND deleted=0', (original['id'],)).fetchone()
                    if item and item['version'] == original['version']:
                        db.execute('UPDATE nodes SET deleted=1 WHERE id=?', (original['id'],))
    status = 'interrupted' if interrupted else 'completed'
    with store.db() as db:
        db.execute('UPDATE runs SET status=?,updated=? WHERE id=?', (status, time.time_ns(), run_id))
    return {'files': changed, 'conflicts': conflicts, 'skipped': skipped, 'status': status}


def recoverable_runs(store, owner, project):
    with store.db() as db:
        store._project(db, owner, project)
        return [dict(row) for row in db.execute(
            "SELECT id,thread,status,created,updated FROM runs WHERE project=? AND status IN ('interrupted','failed') ORDER BY created DESC",
            (project,))]


def recover_run(store, owner, project, run_id):
    """Explicitly import stopped partial output into a separate, owned folder."""
    with store.db() as db:
        store._project(db, owner, project)
        row = db.execute('SELECT * FROM runs WHERE id=? AND project=?', (run_id, project)).fetchone()
        if not row:
            raise WorkspaceError('未完成运行不存在或无权访问。', 404)
        if row['status'] == 'recovered':
            return {'files': [], 'conflicts': [], 'status': 'recovered'}
        if row['status'] not in {'interrupted', 'failed'}:
            raise WorkspaceError('此运行尚不可恢复，请等待运行器停止。', 409)
        run = dict(row)
        work = store.root / 'runs' / run_id / 'workspace'
        files, _, skipped = inspect_outputs(work, max_file_bytes=store.max_file_bytes,
            max_workspace_bytes=store.max_workspace_bytes, max_nodes=store.max_nodes)
        base = json.loads(run['base'])
        changed = {path: content for path, content in files.items()
                   if base.get(path, {}).get('digest') != hashlib.sha256(content).hexdigest()}
        if changed:
            folder = store.create_node(owner, project, '未完成文件-' + run_id[:8], directory=True,
                                       source='agent-recovered', thread=run['thread'], run=run_id)
            run['base'] = '{}'
            result = _reconcile(store, owner, run,
                {folder['name'] + '/' + path: content for path, content in changed.items()}, [], skipped, False)
            db.execute("UPDATE nodes SET source='agent-recovered' WHERE run=? AND project=?", (run_id, project))
            nodes = {node['id']: node for node in store.nodes(owner, project)}
            result['files'] = [nodes[file['id']] for file in result['files']]
        else:
            result = {'files': [], 'conflicts': [], 'skipped': skipped}
        db.execute("UPDATE runs SET status='recovered',updated=? WHERE id=?", (time.time_ns(), run_id))
        return {**result, 'status': 'recovered'}


def fail_run(store, owner, run_id):
    """Release a failed run lease without deleting its recoverable working copy."""
    with store.db() as db:
        row = db.execute('SELECT project FROM runs WHERE id=?', (run_id,)).fetchone()
        if not row:
            raise WorkspaceError('运行不存在。', 404)
        store._project(db, owner, row['project'])
        db.execute("UPDATE runs SET status='failed',updated=? WHERE id=?", (time.time_ns(), run_id))


def discard_completed_copy(store, owner, run_id):
    """After container removal, reclaim only a fully committed execution copy.

    Files and all their versions remain in the private version store. Interrupted
    or failed copies are retained for recovery; they are never removed here.
    """
    if not re.fullmatch(r'[0-9a-f]{32}', run_id):
        raise WorkspaceError('运行标识无效。')
    with store.db() as db:
        run = db.execute('SELECT project,status FROM runs WHERE id=?', (run_id,)).fetchone()
        if not run:
            raise WorkspaceError('运行不存在。', 404)
        store._project(db, owner, run['project'], deleted=True)
        if run['status'] != 'completed':
            return False
        directory = store.root / 'runs' / run_id
        if directory.is_symlink() or directory.resolve() != store.root / 'runs' / run_id:
            raise WorkspaceError('运行副本路径无效。')
        if directory.exists():
            shutil.rmtree(directory)
        return True

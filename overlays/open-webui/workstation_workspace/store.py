"""Workspace metadata and immutable file versions, independent of the UI framework.

Only materialized run directories are exposed to execution containers. The database
and immutable versions never enter an agent mount. All public operations take an
authenticated owner, including operations addressed by an opaque file ID.
"""
from contextlib import contextmanager, suppress
import hashlib
import io
import mimetypes
import os
from pathlib import Path, PurePosixPath
import sqlite3
import stat
import threading
import time
import uuid
import zipfile


class WorkspaceError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def identifier():
    return uuid.uuid4().hex


def valid_name(value):
    if (not isinstance(value, str) or not value.strip() or value in {'.', '..'}
            or len(value.encode('utf-8')) > 240 or any(c in value for c in '/\\:')
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise WorkspaceError('文件名无效。')
    return value


class WorkspaceStore:
    def __init__(self, root, *, max_file_bytes=64 * 1024 * 1024,
                 max_workspace_bytes=512 * 1024 * 1024, max_nodes=5000,
                 max_history_bytes=2 * 1024**3, max_owner_bytes=4 * 1024**3,
                 max_history_versions=20000):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.blobs = self.root / 'versions'
        self.blobs.mkdir(exist_ok=True)
        self.max_file_bytes = max_file_bytes
        self.max_workspace_bytes = max_workspace_bytes
        self.max_nodes = max_nodes
        self.max_history_bytes = max_history_bytes
        self.max_owner_bytes = max_owner_bytes
        self.max_history_versions = max_history_versions
        self._transaction = threading.local()
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL,
                    manual_title INTEGER NOT NULL DEFAULT 0, first_thread TEXT,
                    last_thread TEXT, created INTEGER NOT NULL, updated INTEGER NOT NULL,
                    deleted INTEGER NOT NULL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS project_owner ON projects(owner,deleted,updated);
                CREATE TABLE IF NOT EXISTS threads (
                    id TEXT PRIMARY KEY, project TEXT NOT NULL REFERENCES projects(id),
                    title TEXT NOT NULL, created INTEGER NOT NULL, deleted INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS nodes (
                    id TEXT PRIMARY KEY, project TEXT NOT NULL REFERENCES projects(id),
                    parent TEXT NOT NULL DEFAULT '', name TEXT NOT NULL, kind TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 0, size INTEGER NOT NULL DEFAULT 0,
                    mime TEXT NOT NULL DEFAULT '', source TEXT NOT NULL,
                    thread TEXT, run TEXT, created INTEGER NOT NULL, updated INTEGER NOT NULL,
                    deleted INTEGER NOT NULL DEFAULT 0);
                CREATE UNIQUE INDEX IF NOT EXISTS live_node_path ON nodes(project,parent,name) WHERE deleted=0;
                CREATE INDEX IF NOT EXISTS node_project ON nodes(project);
                CREATE TABLE IF NOT EXISTS versions (
                    node TEXT NOT NULL REFERENCES nodes(id), revision INTEGER NOT NULL,
                    digest TEXT NOT NULL, size INTEGER NOT NULL, created INTEGER NOT NULL,
                    PRIMARY KEY(node,revision));
                CREATE TABLE IF NOT EXISTS imports (
                    project TEXT NOT NULL, source_id TEXT NOT NULL, node TEXT NOT NULL,
                    PRIMARY KEY(project,source_id));
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, project TEXT NOT NULL REFERENCES projects(id),
                    thread TEXT NOT NULL, status TEXT NOT NULL, base TEXT NOT NULL,
                    created INTEGER NOT NULL, updated INTEGER NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_run ON runs(project) WHERE status='running';
            ''')

    @contextmanager
    def db(self):
        # Reconciliation and archive extraction compose the same public
        # operations in one transaction. Savepoints let a version conflict be
        # handled without retaining any partially applied nested operation.
        active = getattr(self._transaction, 'connection', None)
        if active is not None:
            savepoint = 'nested_' + identifier()
            checkpoint = len(self._transaction.writes)
            active.execute('SAVEPOINT ' + savepoint)
            try:
                yield active
                active.execute('RELEASE SAVEPOINT ' + savepoint)
            except BaseException:
                active.execute('ROLLBACK TO SAVEPOINT ' + savepoint)
                active.execute('RELEASE SAVEPOINT ' + savepoint)
                self._discard_uncommitted_writes(checkpoint)
                raise
            return
        db = sqlite3.connect(self.root / 'workspaces.db', timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA busy_timeout=30000')
        try:
            db.execute('BEGIN IMMEDIATE')
            self._transaction.connection = db
            self._transaction.writes = []
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            self._discard_uncommitted_writes(0)
            raise
        finally:
            self._transaction.connection = None
            self._transaction.writes = []
            db.close()

    def _discard_uncommitted_writes(self, checkpoint):
        writes = getattr(self._transaction, 'writes', [])
        for path in reversed(writes[checkpoint:]):
            # These exact paths were created by this transaction in the private
            # version store. No agent-controlled traversal or directory removal.
            with suppress(OSError):
                path.unlink(missing_ok=True)
                path.parent.rmdir()  # Only removes an empty version directory.
        del writes[checkpoint:]

    def _project(self, db, owner, project, *, deleted=False):
        row = db.execute('SELECT * FROM projects WHERE id=? AND owner=?', (project, owner)).fetchone()
        if not row or (row['deleted'] and not deleted):
            raise WorkspaceError('项目不存在或无权访问。', 404)
        return row

    def _node(self, db, owner, node, *, deleted=False):
        row = db.execute('SELECT * FROM nodes WHERE id=?', (node,)).fetchone()
        if not row:
            raise WorkspaceError('文件不存在或无权访问。', 404)
        self._project(db, owner, row['project'])
        if row['deleted'] and not deleted:
            raise WorkspaceError('文件已删除。', 404)
        return row

    def _parent(self, db, owner, project, parent):
        self._project(db, owner, project)
        if parent:
            row = self._node(db, owner, parent)
            if row['project'] != project or row['kind'] != 'directory':
                raise WorkspaceError('目标目录不属于当前项目。')

    def ensure_thread(self, owner, thread, title='新项目', project=None):
        """Idempotent migration/binding. Caller must first verify native chat ownership."""
        if not owner or not thread or len(thread) > 200:
            raise WorkspaceError('缺少有效对话身份。')
        now = time.time_ns()
        with self.db() as db:
            existing = db.execute('SELECT * FROM threads WHERE id=?', (thread,)).fetchone()
            if existing:
                result = self._project(db, owner, existing['project'])
                if project and result['id'] != project:
                    raise WorkspaceError('对话已经属于另一个项目。', 409)
                if existing['deleted']:
                    raise WorkspaceError('对话已删除。', 404)
                db.execute('UPDATE threads SET title=? WHERE id=?', (title, thread))
                if result['first_thread'] == thread and not result['manual_title']:
                    db.execute('UPDATE projects SET title=? WHERE id=?', (title, result['id']))
                return dict(db.execute('SELECT * FROM projects WHERE id=?', (result['id'],)).fetchone())
            if project:
                self._project(db, owner, project)
            else:
                project = identifier()
                db.execute('INSERT INTO projects(id,owner,title,first_thread,last_thread,created,updated) VALUES(?,?,?,?,?,?,?)',
                           (project, owner, title, thread, thread, now, now))
            db.execute('INSERT INTO threads(id,project,title,created) VALUES(?,?,?,?)', (thread, project, title, now))
            db.execute('UPDATE projects SET updated=? WHERE id=?', (now, project))
            return dict(db.execute('SELECT * FROM projects WHERE id=?', (project,)).fetchone())

    def projects(self, owner, *, deleted=False):
        with self.db() as db:
            rows = db.execute('SELECT * FROM projects WHERE owner=? AND deleted=? ORDER BY updated DESC', (owner, int(deleted))).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item['threads'] = [dict(t) for t in db.execute('SELECT * FROM threads WHERE project=? AND deleted=0 ORDER BY created', (row['id'],))]
                result.append(item)
            return result

    def project_for_thread(self, owner, thread, *, remember=False):
        with self.db() as db:
            row = db.execute('SELECT project FROM threads WHERE id=? AND deleted=0', (thread,)).fetchone()
            if not row:
                raise WorkspaceError('对话未绑定工作区。', 404)
            project = self._project(db, owner, row['project'])
            result = dict(project)
            if remember:
                db.execute('UPDATE projects SET last_thread=? WHERE id=?', (thread, project['id']))
                result['last_thread'] = thread
            return result

    def rename_project(self, owner, project, title):
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise WorkspaceError('项目名称需为 1 至 200 个字符。')
        with self.db() as db:
            self._project(db, owner, project)
            db.execute('UPDATE projects SET title=?,manual_title=1,updated=? WHERE id=?', (title.strip(), time.time_ns(), project))

    def delete_thread(self, owner, thread):
        with self.db() as db:
            row = db.execute('SELECT * FROM threads WHERE id=?', (thread,)).fetchone()
            if not row:
                raise WorkspaceError('对话不存在。', 404)
            self._project(db, owner, row['project'])
            if db.execute("SELECT 1 FROM runs WHERE thread=? AND status='running'", (thread,)).fetchone():
                raise WorkspaceError('请先停止当前任务。', 409)
            db.execute('UPDATE threads SET deleted=1 WHERE id=?', (thread,))
            db.execute('UPDATE projects SET last_thread=NULL WHERE id=? AND last_thread=?', (row['project'], thread))

    def delete_project(self, owner, project, *, restore=False):
        with self.db() as db:
            self._project(db, owner, project, deleted=True)
            if db.execute("SELECT 1 FROM runs WHERE project=? AND status='running'", (project,)).fetchone():
                raise WorkspaceError('请先停止当前任务。', 409)
            db.execute('UPDATE projects SET deleted=?,updated=? WHERE id=?', (int(not restore), time.time_ns(), project))

    def _paths(self, rows):
        by_id = {r['id']: dict(r) for r in rows}
        def path(item, seen=None):
            seen = set() if seen is None else seen
            if item['id'] in seen:
                raise WorkspaceError('文件目录关系损坏。', 500)
            seen.add(item['id'])
            parent = item['parent']
            return (path(by_id[parent], seen) + '/' if parent else '') + item['name']
        for item in by_id.values():
            item['path'] = path(item)
        return list(by_id.values())

    def nodes(self, owner, project):
        with self.db() as db:
            self._project(db, owner, project)
            return self._paths(db.execute('SELECT * FROM nodes WHERE project=? AND deleted=0 ORDER BY kind,name', (project,)).fetchall())

    def _unique_name(self, db, project, parent, name):
        candidate, n = name, 1
        while db.execute('SELECT 1 FROM nodes WHERE project=? AND parent=? AND name=? AND deleted=0', (project, parent, candidate)).fetchone():
            stem, suffix = os.path.splitext(name)
            candidate = valid_name(f'{stem[:150]} ({n}){suffix[:30]}')
            n += 1
        return candidate

    def _limits(self, db, project, size, previous=0, new=False):
        row = db.execute('SELECT COUNT(*) AS n,COALESCE(SUM(size),0) AS bytes FROM nodes WHERE project=? AND deleted=0', (project,)).fetchone()
        if size > self.max_file_bytes or row['bytes'] - previous + size > self.max_workspace_bytes or row['n'] + int(new) > self.max_nodes:
            raise WorkspaceError('文件大小或工作区容量达到限制。', 413)

    def _write_version(self, db, node, content, revision):
        project = db.execute('SELECT project FROM nodes WHERE id=?', (node,)).fetchone()['project']
        retained = db.execute('SELECT COALESCE(SUM(v.size),0) bytes,COUNT(*) n FROM versions v JOIN nodes n ON n.id=v.node WHERE n.project=?', (project,)).fetchone()
        owner_bytes = db.execute('SELECT COALESCE(SUM(v.size),0) FROM versions v JOIN nodes n ON n.id=v.node JOIN projects p ON p.id=n.project WHERE p.owner=(SELECT owner FROM projects WHERE id=?)', (project,)).fetchone()[0]
        if retained['bytes'] + len(content) > self.max_history_bytes or retained['n'] + 1 > self.max_history_versions or owner_bytes + len(content) > self.max_owner_bytes:
            raise WorkspaceError('文件版本存储容量达到限制，请联系管理员扩容；已有文件和版本会保留。', 413)
        digest = hashlib.sha256(content).hexdigest()
        directory = self.blobs / node
        directory.mkdir(exist_ok=True)
        target = directory / str(revision)
        temporary = directory / ('pending-' + identifier())
        try:
            temporary.write_bytes(content)
            os.replace(temporary, target)
            self._transaction.writes.append(target)
        finally:
            temporary.unlink(missing_ok=True)
        db.execute('INSERT INTO versions VALUES(?,?,?,?,?)', (node, revision, digest, len(content), time.time_ns()))

    def create_node(self, owner, project, name, *, parent='', content=b'', directory=False,
                    source='upload', thread=None, run=None, source_id=None):
        name = valid_name(name)
        if not isinstance(content, bytes):
            raise WorkspaceError('文件内容格式无效。')
        with self.db() as db:
            self._parent(db, owner, project, parent)
            if source_id:
                old = db.execute('SELECT node FROM imports WHERE project=? AND source_id=?', (project, source_id)).fetchone()
                if old:
                    return dict(db.execute('SELECT * FROM nodes WHERE id=?', (old['node'],)).fetchone())
            if thread:
                linked = db.execute('SELECT 1 FROM threads WHERE id=? AND project=? AND deleted=0', (thread, project)).fetchone()
                if not linked:
                    raise WorkspaceError('文件来源对话不属于当前项目。')
            self._limits(db, project, 0 if directory else len(content), new=True)
            name = self._unique_name(db, project, parent, name)
            node, now = identifier(), time.time_ns()
            mime = '' if directory else (mimetypes.guess_type(name)[0] or 'application/octet-stream')
            db.execute('INSERT INTO nodes(id,project,parent,name,kind,version,size,mime,source,thread,run,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (node, project, parent, name, 'directory' if directory else 'file', 0 if directory else 1,
                        0 if directory else len(content), mime, source, thread, run, now, now))
            if not directory:
                self._write_version(db, node, content, 1)
            if source_id:
                db.execute('INSERT INTO imports VALUES(?,?,?)', (project, source_id, node))
            db.execute('UPDATE projects SET updated=? WHERE id=?', (now, project))
            return dict(db.execute('SELECT * FROM nodes WHERE id=?', (node,)).fetchone())

    def read(self, owner, node, revision=None):
        with self.db() as db:
            item = self._node(db, owner, node)
            if item['kind'] != 'file':
                raise WorkspaceError('目录不能作为文件读取。')
            revision = item['version'] if revision is None else revision
            record = db.execute('SELECT * FROM versions WHERE node=? AND revision=?', (node, revision)).fetchone()
            if not record:
                raise WorkspaceError('文件版本不存在。', 404)
            content = (self.blobs / item['id'] / str(record['revision'])).read_bytes()
            if hashlib.sha256(content).hexdigest() != record['digest']:
                raise WorkspaceError('文件完整性检查失败。', 500)
            return dict(item), content

    def versions(self, owner, node):
        with self.db() as db:
            self._node(db, owner, node)
            return [dict(r) for r in db.execute('SELECT revision,size,created FROM versions WHERE node=? ORDER BY revision DESC', (node,))]

    def edit(self, owner, node, content, expected_version, *, source=None, thread=None, run=None):
        if not isinstance(content, bytes):
            raise WorkspaceError('文件内容格式无效。')
        with self.db() as db:
            item = self._node(db, owner, node)
            if item['kind'] != 'file':
                raise WorkspaceError('目录不能编辑内容。')
            if item['version'] != expected_version:
                raise WorkspaceError('文件已被修改，请保留草稿并重新载入或合并。', 409)
            if thread and not db.execute('SELECT 1 FROM threads WHERE id=? AND project=?', (thread, item['project'])).fetchone():
                raise WorkspaceError('文件来源对话不属于当前项目。')
            self._limits(db, item['project'], len(content), item['size'])
            revision = item['version'] + 1
            self._write_version(db, node, content, revision)
            db.execute('UPDATE nodes SET version=?,size=?,updated=? WHERE id=?', (revision, len(content), time.time_ns(), node))
            if source:
                db.execute('UPDATE nodes SET source=?,thread=?,run=? WHERE id=?', (source, thread, run, node))
            return dict(db.execute('SELECT * FROM nodes WHERE id=?', (node,)).fetchone())

    def move(self, owner, node, *, name, parent=''):
        name = valid_name(name)
        with self.db() as db:
            item = self._node(db, owner, node)
            self._parent(db, owner, item['project'], parent)
            ancestor = parent
            while ancestor:
                if ancestor == node:
                    raise WorkspaceError('不能将目录移动到自身内部。')
                ancestor = db.execute('SELECT parent FROM nodes WHERE id=?', (ancestor,)).fetchone()['parent']
            other = db.execute('SELECT id FROM nodes WHERE project=? AND parent=? AND name=? AND deleted=0', (item['project'], parent, name)).fetchone()
            if other and other['id'] != node:
                raise WorkspaceError('目标位置已有同名文件。', 409)
            mime = '' if item['kind'] == 'directory' else (mimetypes.guess_type(name)[0] or 'application/octet-stream')
            db.execute('UPDATE nodes SET parent=?,name=?,mime=?,updated=? WHERE id=?', (parent, name, mime, time.time_ns(), node))

    def delete_node(self, owner, node):
        with self.db() as db:
            self._node(db, owner, node)
            db.execute('WITH RECURSIVE subtree(id) AS (SELECT ? UNION ALL SELECT n.id FROM nodes n JOIN subtree s ON n.parent=s.id WHERE n.deleted=0) UPDATE nodes SET deleted=1 WHERE id IN (SELECT id FROM subtree)', (node,))

    def extract_zip(self, owner, node):
        item, content = self.read(owner, node)
        entries, total = [], 0
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                if len(archive.infolist()) > min(self.max_nodes, 1000):
                    raise WorkspaceError('压缩包包含过多文件。', 413)
                for info in archive.infolist():
                    path = PurePosixPath(info.filename)
                    mode = info.external_attr >> 16
                    if (path.is_absolute() or not path.parts or '\\' in info.filename or ':' in info.filename
                            or any(p in {'.', '..'} for p in info.filename.split('/') if p)
                            or stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR})):
                        raise WorkspaceError('压缩包包含不安全路径或特殊文件。')
                    for part in path.parts:
                        valid_name(part)
                    total += info.file_size
                    if info.file_size > self.max_file_bytes or total > self.max_workspace_bytes:
                        raise WorkspaceError('压缩包解压体积超过限制。', 413)
                    entries.append((path.parts, None if info.is_dir() else archive.read(info)))
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError):
            raise WorkspaceError('压缩包无效、加密或格式不受支持。') from None
        # Validate the entire archive before creating anything. Extract into its
        # own folder, so it never overwrites existing workspace files.
        with self.db() as db:
            self._project(db, owner, item['project'])
            used = db.execute('SELECT COALESCE(SUM(size),0) AS bytes FROM nodes WHERE project=? AND deleted=0', (item['project'],)).fetchone()['bytes']
            if used + total > self.max_workspace_bytes:
                raise WorkspaceError('工作区容量达到限制。', 413)
            folder = self.create_node(owner, item['project'], Path(item['name']).stem[:180] or '解压文件', parent=item['parent'], directory=True)
            dirs = {(): folder['id']}
            for parts, data in entries:
                for n in range(1, len(parts) + (data is None)):
                    prefix = parts[:n]
                    if prefix not in dirs:
                        dirs[prefix] = self.create_node(owner, item['project'], prefix[-1], parent=dirs[prefix[:-1]], directory=True)['id']
                if data is not None:
                    self.create_node(owner, item['project'], parts[-1], parent=dirs[parts[:-1]], content=data, source='extract')
            return folder

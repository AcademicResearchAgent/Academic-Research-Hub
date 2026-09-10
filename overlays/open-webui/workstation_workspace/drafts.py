"""Draft promotion helpers: empty navigation is not persistent user work."""
from .store import WorkspaceError


def has_messages(document):
    history = document.get('history') or {}
    nested = history.get('messages') or {} if isinstance(history, dict) else {}
    messages = list(nested.values()) if isinstance(nested, dict) else []
    if isinstance(document.get('messages'), list):
        messages += document['messages']
    return any(isinstance(message, dict) and (
        bool(str(message.get('content') or '').strip()) or bool(message.get('files'))
    ) for message in messages)


def first_title(document, attachments):
    history = document.get('history') or {}
    entries = history.get('messages') or {} if isinstance(history, dict) else {}
    messages = entries.values() if isinstance(entries, dict) else []
    for message in messages:
        if isinstance(message, dict) and message.get('role') == 'user' and isinstance(message.get('content'), str) and message['content'].strip():
            return ' '.join(message['content'].split())[:60]
    if attachments:
        return attachments[0]['name'][:200]
    raise WorkspaceError('发送消息或上传文件后才会创建项目。')


def promote(store, owner, thread, title, project, attachments):
    # Binding and all original file imports share one transaction. A rejected
    # upload must not leave an empty project or a partially imported file set.
    with store.db():
        result = store.ensure_thread(owner, thread, title, project)
        for file in attachments:
            store.create_node(owner, result['id'], file['name'], content=file['content'],
                              source='upload', thread=thread, source_id='webui:' + file['id'])
        return result

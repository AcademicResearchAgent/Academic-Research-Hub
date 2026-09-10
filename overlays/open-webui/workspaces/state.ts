import { get, writable } from 'svelte/store';
import { user } from '$lib/stores';

export type WorkspaceFile = { id: string; project: string; parent: string; name: string; path: string;
    kind: 'file' | 'directory'; version: number; size: number; mime: string; source: string };
export type Project = { id: string; title: string; last_thread?: string; threads: {id: string; title: string}[] };
export const projects = writable<Project[]>([]);
export const activeProject = writable<string>('');
export const nodes = writable<WorkspaceFile[]>([]);
export const selectedFile = writable<WorkspaceFile | null>(null);
export const workspaceError = writable('');
export const workspaceRefresh = writable(0);
export const drafts = new Map<string, {content: string; version: number}>();
let owner = '';
let session = new AbortController();
let selectionVersion = 0;
user.subscribe(value => resetWorkspace(value?.id ?? ''));
selectedFile.subscribe(file => {
    if (file && owner && typeof localStorage !== 'undefined')
        localStorage.setItem('workspace-view:' + owner + ':' + file.project, file.id);
});

export function resetWorkspace(userId: string) {
    if (owner === userId) return;
    owner = userId;
    session.abort(); session = new AbortController(); selectionVersion++;
    projects.set([]); activeProject.set(''); nodes.set([]); selectedFile.set(null);
    workspaceError.set(''); drafts.clear();
}

export async function api(path: string, init: RequestInit = {}) {
    const currentOwner = owner;
    const headers = new Headers(init.headers);
    headers.set('Authorization', 'Bearer ' + localStorage.token);
    if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json');
    const response = await fetch('/api/workstation' + path, {...init, headers, signal: session.signal, credentials: 'same-origin'});
    if (currentOwner !== owner) throw new DOMException('Account changed', 'AbortError');
    if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(typeof error.detail === 'string' ? error.detail : '文件服务暂不可用，请重试。');
    }
    return response;
}

export async function refreshProjects() {
    const requestOwner = owner;
    const data = await (await api('/projects')).json();
    if (requestOwner !== owner) return;
    projects.set(data);
}

export async function refreshFiles(project = get(activeProject)) {
    if (!project) return;
    const version = selectionVersion;
    const data = await (await api('/projects/' + project + '/files')).json();
    if (project !== get(activeProject) || version !== selectionVersion) return;
    nodes.set(data);
    const current = get(selectedFile);
    if (current) {
        const next = data.find((n: WorkspaceFile) => n.id === current.id);
        if (next) selectedFile.set(next);
        else selectedFile.set(null);
    }
}

export async function selectProject(project: string) {
    const changedProject = get(activeProject) !== project;
    if (changedProject) {
        selectionVersion++;
        activeProject.set(project); nodes.set([]); selectedFile.set(null);
    }
    await refreshFiles(project);
    if (changedProject && project === get(activeProject)) {
        const saved = localStorage.getItem('workspace-view:' + owner + ':' + project);
        selectedFile.set(get(nodes).find(n=>n.id===saved) ?? null);
    }
}

export async function selectThread(thread: string) {
    if (!thread || thread.startsWith('local:')) return;
    const version = ++selectionVersion;
    const project = await (await api('/threads/' + encodeURIComponent(thread) + '/open', {method: 'POST'})).json();
    if (version !== selectionVersion) return;
    await selectProject(project.id);
    await refreshProjects();
}

export async function openWorkspaceFile(id: string, project?: string) {
    if (project && project !== get(activeProject)) await selectProject(project);
    await refreshFiles();
    const node = get(nodes).find(n => n.id === id);
    if (!node) throw new Error('文件已删除或不属于当前项目。');
    selectedFile.set(node);
}

export function changed() { workspaceRefresh.update(n => n + 1); }

export function clearSelection() {
    selectionVersion++;
    activeProject.set(''); nodes.set([]); selectedFile.set(null);
}

export async function downloadFile(file: WorkspaceFile, revision?: number) {
    const requestOwner = owner;
    const response = await api('/files/' + file.id + '/content' + (revision ? '?revision=' + revision : ''));
    const blob = await response.blob();
    if (requestOwner !== owner) return;
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = file.name; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}

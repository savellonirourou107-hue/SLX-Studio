import { app, BrowserWindow, dialog, ipcMain, Menu, protocol, session } from 'electron';
import type { IpcMainInvokeEvent } from 'electron';
import { createHash, randomUUID } from 'node:crypto';
import * as fs from 'node:fs/promises';
import path from 'node:path';
import { PythonBackend } from './backend';
import type { Draft, Result, WorkspaceInfo } from '../../../packages/protocol';

const origin = 'slx-app://workbench';
const sourceRoot = path.resolve(__dirname, '../../..');
const assets = path.resolve(__dirname, '../renderer');
const stateRoot = path.resolve(process.env.SLX_DESKTOP_STATE_DIR || path.join(app.getPath('userData'), 'slx-studio-2'));
app.setPath('userData', stateRoot);
app.setPath('sessionData', path.join(stateRoot, 'chromium'));
app.setPath('crashDumps', path.join(stateRoot, 'crashes'));
app.setAppLogsPath(path.join(stateRoot, 'logs'));
protocol.registerSchemesAsPrivileged([{ scheme: 'slx-app', privileges: { standard: true, secure: true, supportFetchAPI: true, corsEnabled: true, codeCache: true } }]);
let window: BrowserWindow;
let backend: PythonBackend | null = null;
let workspace: WorkspaceInfo | null = null;
let closing = false;
const draftQueues = new Map<string, Promise<unknown>>();

function validate(event: IpcMainInvokeEvent): void {
  if (!window || event.sender !== window.webContents || event.senderFrame !== window.webContents.mainFrame || event.senderFrame.url !== `${origin}/index.html`) throw new Error('Untrusted IPC sender');
}
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Expected an object');
  return value as Record<string, unknown>;
}
function text(value: unknown, max = 4096): string {
  if (typeof value !== 'string' || value.length > max || value.includes('\0')) throw new Error('Invalid text argument');
  return value;
}
function backendRequired(): PythonBackend {
  if (!backend) throw new Error('Open a workspace first');
  return backend;
}
function handle<T>(channel: string, callback: (payload: unknown) => Promise<T>): void {
  ipcMain.handle(channel, async (event, payload): Promise<Result<T>> => {
    try { validate(event); return { ok: true, value: await callback(payload) }; }
    catch (error) {
      const failure = error as Error & { kind?: string };
      return { ok: false, error: failure.message, kind: failure.kind || 'desktop' };
    }
  });
}
async function openWorkspace(folder: string): Promise<WorkspaceInfo> {
  const info = await fs.stat(folder);
  if (!info.isDirectory() && path.extname(folder).toLowerCase() !== '.m') throw new Error('Select a folder or MATLAB script');
  const candidate = new PythonBackend(process.env.SLX_STUDIO_PYTHON || 'python', folder, sourceRoot, path.join(stateRoot, 'python'));
  try {
    const initialized = await candidate.request<WorkspaceInfo>('initialize');
    if (initialized.protocol_version !== 1) throw new Error('Unsupported Python backend version');
    backend?.close();
    backend = candidate;
    workspace = initialized;
    return initialized;
  } catch (error) { candidate.close(); throw error; }
}
function draftFile(relative: string): string {
  if (!workspace) throw new Error('No workspace');
  const key = createHash('sha256').update(`${workspace.root}\n${relative}`).digest('hex');
  return path.join(stateRoot, 'drafts', `${key}.json`);
}
function queueDraft<T>(file: string, work: () => Promise<T>): Promise<T> {
  const next = (draftQueues.get(file) || Promise.resolve()).catch(() => {}).then(work);
  draftQueues.set(file, next);
  void next.finally(() => { if (draftQueues.get(file) === next) draftQueues.delete(file); }).catch(() => {});
  return next;
}

async function start(): Promise<void> {
  await fs.mkdir(path.join(stateRoot, 'chromium'), { recursive: true });
  await app.whenReady();
  session.defaultSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  session.defaultSession.setPermissionCheckHandler(() => false);
  session.defaultSession.webRequest.onBeforeRequest((details, callback) => callback({ cancel: !details.url.startsWith(`${origin}/`) && !details.url.startsWith('blob:slx-app://workbench/') && !details.url.startsWith('data:') }));
  protocol.handle('slx-app', async request => {
    try {
      const url = new URL(request.url);
      if (url.host !== 'workbench' || request.method !== 'GET') return new Response('Forbidden', { status: 403 });
      const relative = decodeURIComponent(url.pathname).slice(1);
      if (!relative || relative.includes('\\') || relative.split('/').some(part => !part || part === '..' || part === '.') || relative.includes(':')) return new Response('Invalid asset', { status: 400 });
      const filename = path.resolve(assets, relative);
      const extension = path.extname(filename);
      const types: Record<string, string> = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.ttf': 'font/ttf', '.woff': 'font/woff', '.woff2': 'font/woff2' };
      if (!filename.startsWith(assets + path.sep) || !types[extension]) return new Response('Not found', { status: 404 });
      const contents = await fs.readFile(filename);
      return new Response(contents, { headers: { 'Content-Type': types[extension], 'X-Content-Type-Options': 'nosniff' } });
    } catch { return new Response('Not found', { status: 404 }); }
  });
  window = new BrowserWindow({
    width: 1360, height: 900, minWidth: 800, minHeight: 540, show: false,
    title: 'SLX Studio 2.0 · Development', backgroundColor: '#13191f',
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true, sandbox: true, nodeIntegration: false, webSecurity: true, spellcheck: false },
  });
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.webContents.on('will-navigate', event => event.preventDefault());
  window.webContents.on('will-attach-webview', event => event.preventDefault());
  window.on('close', event => { if (!closing) { event.preventDefault(); window.webContents.send('slx:closeRequested'); } });
  window.on('closed', () => backend?.close());
  window.once('ready-to-show', () => { if (process.env.SLX_DESKTOP_TEST_HIDE !== '1') window.show(); });
  const sendCommand = (id: string) => () => window.webContents.send('slx:command', id);
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    { label: 'File', submenu: [
      { label: 'Open Folder…', click: sendCommand('workspace.open') },
      { label: 'Save', click: sendCommand('file.save') },
      { label: 'Close Editor', click: sendCommand('file.close') },
      { type: 'separator' }, { label: 'Exit', click: () => window.close() },
    ] },
    { label: 'Edit', submenu: [{ role: 'undo' }, { role: 'redo' }, { type: 'separator' }, { role: 'cut' }, { role: 'copy' }, { role: 'paste' }, { role: 'selectAll' }] },
    { label: 'View', submenu: [{ label: 'Command Palette…', click: sendCommand('workbench.palette') }, { role: 'toggleDevTools' }] },
  ]));
  handle('slx:workspace', async () => workspace);
  handle('slx:chooseWorkspace', async () => {
    const selected = await dialog.showOpenDialog(window, { properties: ['openDirectory'] });
    return selected.canceled ? null : openWorkspace(selected.filePaths[0]);
  });
  handle('slx:list', async payload => {
    const args = object(payload);
    if (!Number.isSafeInteger(args.cursor) || (args.cursor as number) < 0) throw new Error('Invalid cursor');
    return backendRequired().request('workspace/listDirectory', { relative: text(args.path), cursor: args.cursor });
  });
  handle('slx:read', async payload => backendRequired().request('document/read', { relative: text(object(payload).path) }));
  handle('slx:save', async payload => {
    const args = object(payload);
    if (typeof args.bom !== 'boolean' || !/^[a-f0-9]{64}$/.test(text(args.hash, 64))) throw new Error('Invalid save version');
    return backendRequired().request('document/save', { relative: text(args.path), content: text(args.content, 4 * 1024 * 1024), expected_sha256: args.hash, bom: args.bom });
  });
  handle('slx:loadDraft', async payload => {
    const relative = text(object(payload).path);
    const file = draftFile(relative);
    return queueDraft(file, async () => {
      try {
        const info = await fs.stat(file);
        if (info.size > 12 * 1024 * 1024) throw new Error('Recovery record exceeds size limit');
        const draft = JSON.parse(await fs.readFile(file, 'utf8')) as Draft;
        if (draft.path !== relative || typeof draft.content !== 'string' || draft.base?.path !== relative || typeof draft.base.sha256 !== 'string') throw new Error('Invalid recovery record');
        return draft;
      } catch (error) { if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null; throw error; }
    });
  });
  handle('slx:storeDraft', async payload => {
    const args = object(payload);
    const relative = text(args.path);
    const file = draftFile(relative);
    // Clearing a hashed recovery record must still work after its source was deleted.
    // New draft content requires a verified root-scoped document target.
    if (args.clear !== true) await backendRequired().request('document/read', { relative });
    await queueDraft(file, async () => {
      if (args.clear === true) { await fs.rm(file, { force: true }); return; }
      const base = object(args.base);
      if (base.path !== relative || !/^[a-f0-9]{64}$/.test(text(base.sha256, 64))) throw new Error('Invalid draft base');
      const data = JSON.stringify({ path: relative, content: text(args.content, 4 * 1024 * 1024), base });
      if (Buffer.byteLength(data) > 12 * 1024 * 1024) throw new Error('Recovery record exceeds size limit');
      await fs.mkdir(path.dirname(file), { recursive: true });
      const temp = `${file}.${randomUUID()}.tmp`;
      try { await fs.writeFile(temp, data, { flag: 'wx', mode: 0o600 }); await fs.rename(temp, file); }
      finally { await fs.rm(temp, { force: true }); }
    });
    return null;
  });
  ipcMain.on('slx:closeConfirmed', event => {
    try { validate(event as IpcMainInvokeEvent); closing = true; window.close(); } catch { /* Reject foreign frames. */ }
  });
  if (process.env.SLX_DESKTOP_WORKSPACE) await openWorkspace(process.env.SLX_DESKTOP_WORKSPACE);
  await window.loadURL(`${origin}/index.html`);
}
app.on('window-all-closed', () => app.quit());
app.on('before-quit', () => backend?.close());
void start().catch(error => { process.stderr.write(`SLX desktop startup failed: ${String(error)}\n`); app.exit(1); });

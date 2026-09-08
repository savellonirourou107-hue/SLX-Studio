import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import * as fs from 'node:fs/promises';
import * as fsSync from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';

export interface ExtensionCommand { command: string; title: string; }
export interface ExtensionView { id: string; title: string; location: 'activity' | 'sidebar' | 'panel'; }
export interface ExtensionEditor { id: string; label: string; extensions: string[]; }
export interface ExtensionManifest {
  id: string; apiVersion: 1; version: string; main: string; activationEvents: string[];
  contributes: { commands: ExtensionCommand[]; views: ExtensionView[]; editors: ExtensionEditor[] };
}
export interface ExtensionRecord extends ExtensionManifest { path: string; state: 'inactive' | 'activating' | 'active' | 'failed'; error?: string; }

const MAX_MANIFEST_BYTES = 64 * 1024;
const MAX_MESSAGE_BYTES = 512 * 1024;
const REQUEST_TIMEOUT_MS = 5000;
const ID = /^[a-z][a-z0-9]*(?:\.[a-z][a-z0-9]*)+$/;
const WORKER_SOURCE = String.raw`
const fs = require('node:fs');
const readline = require('node:readline');
let extension = null;
const send = value => process.stdout.write(JSON.stringify(value) + '\n');
const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
rl.on('line', async line => {
  if (Buffer.byteLength(line, 'utf8') > ${MAX_MESSAGE_BYTES}) return send({ id: null, ok: false, error: 'message too large' });
  let request;
  try { request = JSON.parse(line); } catch { return send({ id: null, ok: false, error: 'invalid message' }); }
  try {
    if (request.op === 'activate') {
      extension = await import(require('node:url').pathToFileURL(request.main).href);
      const value = typeof extension.activate === 'function' ? await extension.activate({ extensionId: request.extensionId }) : {};
      send({ id: request.id, ok: true, contributions: value && typeof value === 'object' ? value : {} });
    } else if (request.op === 'execute') {
      if (!extension || typeof extension.execute !== 'function') throw new Error('extension has no execute export');
      const value = await extension.execute(request.command, request.args ?? {});
      send({ id: request.id, ok: true, value: value === undefined ? null : value });
    } else if (request.op === 'shutdown') {
      if (extension && typeof extension.deactivate === 'function') await extension.deactivate();
      send({ id: request.id, ok: true });
      process.exit(0);
    } else throw new Error('unknown extension operation');
  } catch (error) { send({ id: request.id, ok: false, error: String(error && error.message || error) }); }
});
`;

function object(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${label} must be an object`);
  return value as Record<string, unknown>;
}
function boundedText(value: unknown, label: string, max: number): string {
  if (typeof value !== 'string' || !value || value.length > max || value.includes('\0')) throw new Error(`invalid ${label}`);
  return value;
}
function arrayOf<T>(value: unknown, label: string, parser: (item: unknown) => T, max = 64): T[] {
  if (value === undefined) return [];
  if (!Array.isArray(value) || value.length > max) throw new Error(`invalid ${label}`);
  return value.map(parser);
}
function safePath(root: string, relative: string): string {
  if (path.isAbsolute(relative) || relative.includes('\0') || relative.includes('\\') || relative.split('/').some(part => !part || part === '.' || part === '..')) throw new Error('extension manifest path must be a simple relative path');
  const resolved = path.resolve(root, relative);
  if (!resolved.startsWith(`${path.resolve(root)}${path.sep}`)) throw new Error('extension path escapes trusted root');
  return resolved;
}
async function regularFile(filename: string): Promise<void> {
  const info = await fs.lstat(filename);
  if (!info.isFile()) throw new Error('extension target must be a regular file');
}
function parseCommand(value: unknown): ExtensionCommand {
  const item = object(value, 'command');
  const command = boundedText(item.command, 'command id', 128);
  const title = boundedText(item.title, 'command title', 256);
  if (!ID.test(command)) throw new Error('invalid extension command id');
  return { command, title };
}
function parseView(value: unknown): ExtensionView {
  const item = object(value, 'view');
  const id = boundedText(item.id, 'view id', 128);
  const title = boundedText(item.title, 'view title', 256);
  const location = item.location;
  if (!ID.test(id) || !['activity', 'sidebar', 'panel'].includes(String(location))) throw new Error('invalid extension view');
  return { id, title, location: location as ExtensionView['location'] };
}
function parseEditor(value: unknown): ExtensionEditor {
  const item = object(value, 'editor');
  const id = boundedText(item.id, 'editor id', 128);
  const label = boundedText(item.label, 'editor label', 256);
  const extensions = arrayOf(item.extensions, 'editor extensions', entry => {
    const extension = boundedText(entry, 'editor extension', 16);
    if (!/^\.[a-z0-9][a-z0-9-]{0,15}$/i.test(extension)) throw new Error('invalid extension suffix');
    return extension.toLowerCase();
  }, 16);
  if (!ID.test(id) || !extensions.length) throw new Error('invalid extension editor');
  return { id, label, extensions };
}

export class ExtensionHostManager {
  private readonly records = new Map<string, ExtensionRecord>();
  private readonly children = new Map<string, ChildProcessWithoutNullStreams>();
  private readonly pending = new Map<string, { resolve: (value: any) => void; reject: (error: Error) => void; timer: NodeJS.Timeout }>();
  private readonly buffers = new Map<string, string>();
  constructor(private readonly trustedRoot: string) {}

  async discover(): Promise<readonly ExtensionRecord[]> {
    const root = path.resolve(this.trustedRoot);
    const entries = await fs.readdir(root, { withFileTypes: true }).catch(() => [] as fsSync.Dirent[]);
    for (const entry of entries) {
      if (!entry.isDirectory() || entry.name.startsWith('.')) continue;
      const directory = safePath(root, entry.name);
      let record: ExtensionRecord;
      try {
        const manifestPath = safePath(directory, 'slx-extension.json');
        const info = await fs.stat(manifestPath);
        if (info.size > MAX_MANIFEST_BYTES) throw new Error('manifest exceeds 64 KiB');
        const raw = object(JSON.parse(await fs.readFile(manifestPath, 'utf8')), 'manifest');
        if (raw.apiVersion !== 1) throw new Error('unsupported extension API version');
        const id = boundedText(raw.id, 'extension id', 128);
        if (!ID.test(id) || id !== entry.name) throw new Error('extension directory must match manifest id');
        const main = boundedText(raw.main, 'extension main', 128);
        const mainPath = safePath(directory, main);
        await regularFile(mainPath);
        const contributes = object(raw.contributes ?? {}, 'contributes');
        record = {
          id, apiVersion: 1, version: boundedText(raw.version, 'extension version', 64), main,
          activationEvents: arrayOf(raw.activationEvents, 'activation events', item => boundedText(item, 'activation event', 128)),
          contributes: {
            commands: arrayOf(contributes.commands, 'commands', parseCommand),
            views: arrayOf(contributes.views, 'views', parseView),
            editors: arrayOf(contributes.editors, 'editors', parseEditor),
          }, path: directory, state: 'inactive',
        };
      } catch (error) {
        const id = `${entry.name}`;
        record = { id, apiVersion: 1, version: 'invalid', main: '', activationEvents: [], contributes: { commands: [], views: [], editors: [] }, path: directory, state: 'failed', error: String((error as Error).message || error) };
      }
      this.records.set(record.id, record);
    }
    return this.list();
  }
  list(): readonly ExtensionRecord[] { return [...this.records.values()].map(record => ({ ...record, contributes: { commands: [...record.contributes.commands], views: [...record.contributes.views], editors: [...record.contributes.editors] } })); }
  private record(id: string): ExtensionRecord {
    const record = this.records.get(id);
    if (!record) throw new Error(`Unknown extension: ${id}`);
    if (record.state === 'failed') throw new Error(record.error || `Extension ${id} is invalid`);
    return record;
  }
  private request(id: string, operation: Record<string, unknown>): Promise<any> {
    const child = this.children.get(id);
    if (!child || child.exitCode !== null) return Promise.reject(new Error('extension host is not running'));
    const requestId = randomUUID();
    const payload = JSON.stringify({ id: requestId, ...operation });
    if (Buffer.byteLength(payload, 'utf8') > MAX_MESSAGE_BYTES) return Promise.reject(new Error('extension request exceeds size limit'));
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(requestId); reject(new Error('extension host request timed out')); }, REQUEST_TIMEOUT_MS);
      this.pending.set(requestId, { resolve, reject, timer });
      child.stdin.write(`${payload}\n`);
    });
  }
  async activate(id: string): Promise<ExtensionRecord> {
    const record = this.record(id);
    if (record.state === 'active') return { ...record };
    record.state = 'activating';
    try {
      const mainPath = safePath(record.path, record.main);
      await regularFile(mainPath);
      const child = spawn(process.execPath, ['--disallow-code-generation-from-strings', '-e', WORKER_SOURCE], {
        cwd: record.path, windowsHide: true, shell: false,
        // Electron's binary only behaves as a Node child when this flag is
        // present. Plain Node test hosts keep their inherited environment.
        env: { ...process.env, ...(process.versions.electron ? { ELECTRON_RUN_AS_NODE: '1' } : {}) },
        stdio: ['pipe', 'pipe', 'pipe'],
      });
      this.children.set(id, child);
      this.buffers.set(id, '');
      child.stdout.setEncoding('utf8');
      child.stdout.on('data', (chunk: string) => this.handleOutput(id, chunk));
      child.stderr.on('data', () => { /* extension diagnostics are intentionally not surfaced as executable output */ });
      child.on('error', error => this.fail(id, error));
      child.on('exit', (_code, signal) => { if (this.children.get(id) === child) { this.children.delete(id); if (record.state === 'active') { record.state = 'failed'; record.error = `extension host exited${signal ? ` (${signal})` : ''}`; } this.fail(id, new Error(record.error || 'extension host exited')); } });
      const response = await this.request(id, { op: 'activate', extensionId: id, main: mainPath });
      if (!response?.ok) throw new Error(String(response?.error || 'extension activation failed'));
      record.state = 'active';
      return { ...record };
    } catch (error) {
      record.state = 'failed'; record.error = String((error as Error).message || error);
      await this.deactivate(id);
      throw error;
    }
  }
  async execute(id: string, command: string, args: Record<string, unknown> = {}): Promise<unknown> {
    const record = this.record(id);
    if (record.state !== 'active') throw new Error(`Extension ${id} is not active`);
    if (!record.contributes.commands.some(item => item.command === command)) throw new Error('command is not contributed by extension');
    const response = await this.request(id, { op: 'execute', command, args });
    if (!response?.ok) throw new Error(String(response?.error || 'extension command failed'));
    return response.value;
  }
  async deactivate(id: string): Promise<void> {
    const record = this.records.get(id);
    const child = this.children.get(id);
    if (record && record.state !== 'failed') record.state = 'inactive';
    if (child) {
      const exited = child.exitCode !== null ? Promise.resolve() : new Promise<void>(resolve => child.once('exit', () => resolve()));
      try { await this.request(id, { op: 'shutdown' }); } catch { /* kill below */ }
      if (child.exitCode === null) child.kill();
      await Promise.race([exited, new Promise<void>(resolve => setTimeout(resolve, 1000))]);
      this.children.delete(id);
    }
    this.fail(id, new Error('extension host stopped'));
  }
  async close(): Promise<void> { for (const id of [...this.records.keys()]) await this.deactivate(id); }
  private handleOutput(id: string, chunk: string): void {
    let buffer = (this.buffers.get(id) || '') + chunk;
    if (buffer.length > MAX_MESSAGE_BYTES * 2) { this.fail(id, new Error('extension host output exceeded limit')); this.children.get(id)?.kill(); return; }
    const lines = buffer.split('\n'); buffer = lines.pop() || ''; this.buffers.set(id, buffer);
    for (const line of lines) {
      if (!line) continue;
      try {
        const response = JSON.parse(line); const request = this.pending.get(response.id);
        if (!request) continue;
        this.pending.delete(response.id); clearTimeout(request.timer); request.resolve(response);
      } catch { /* malformed host output is ignored until a request times out */ }
    }
  }
  private fail(id: string, error: Error): void {
    for (const [requestId, request] of this.pending) { clearTimeout(request.timer); request.reject(error); this.pending.delete(requestId); }
  }
}

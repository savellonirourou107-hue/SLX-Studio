import * as fs from 'node:fs/promises';
import path from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { ConfigurationStore, DESKTOP_SCHEMAS } from '../../../packages/configuration';
import type { ConfigurationScope } from '../../../packages/configuration';
import type { ConfigurationFile, ConfigurationState, ConfigurationValue } from '../../../packages/protocol';

const MAX_BYTES = 64 * 1024;
const hash = (raw: Buffer) => createHash('sha256').update(raw).digest('hex');
const missing = (scope: ConfigurationScope): ConfigurationFile => ({ scope, exists: false, sha256: null, values: {}, issues: [] });

/** Fixed filenames only. Workspace files never select executables or grant trust. */
export class ConfigurationFiles {
  private queue: Promise<unknown> = Promise.resolve();
  constructor(private readonly stateRoot: string) {}

  private async filename(scope: ConfigurationScope, workspaceRoot: string | null, create = false): Promise<string> {
    const directory = scope === 'user' ? this.stateRoot : workspaceRoot && path.join(workspaceRoot, '.slx-studio');
    if (!directory) throw new Error('Open a workspace before using workspace settings');
    let info;
    try { info = await fs.lstat(directory); }
    catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
      if (!create) return path.join(directory, 'settings.json');
      // Workspace root is already selected/canonicalized by the Python adapter.
      try { await fs.mkdir(directory, { recursive: scope === 'user', mode: 0o700 }); }
      catch (failure) { if ((failure as NodeJS.ErrnoException).code !== 'EEXIST') throw failure; }
      info = await fs.lstat(directory);
    }
    if (!info.isDirectory() || info.isSymbolicLink()) throw new Error('Settings directory must not be a link or junction');
    return path.join(directory, 'settings.json');
  }

  private async readLayer(scope: ConfigurationScope, workspaceRoot: string | null): Promise<{ file: ConfigurationFile; values: unknown }> {
    let file = missing(scope);
    if (scope === 'workspace' && !workspaceRoot) return { file, values: {} };
    try {
      const filename = await this.filename(scope, workspaceRoot);
      let before;
      try { before = await fs.lstat(filename); }
      catch (error) { if ((error as NodeJS.ErrnoException).code === 'ENOENT') return { file, values: {} }; throw error; }
      file = { ...file, exists: true };
      if (!before.isFile() || before.isSymbolicLink()) throw new Error('Settings must be a regular file, not a link');
      if (before.size > MAX_BYTES) throw new Error('Settings exceed the 64 KiB limit');
      const handle = await fs.open(filename, 'r');
      const buffer = Buffer.alloc(MAX_BYTES + 1);
      let length = 0;
      try {
        while (length < buffer.length) {
          const { bytesRead } = await handle.read(buffer, length, buffer.length - length, length);
          if (!bytesRead) break;
          length += bytesRead;
        }
      } finally { await handle.close(); }
      if (length > MAX_BYTES) throw new Error('Settings exceed the 64 KiB limit');
      const after = await fs.lstat(filename);
      if (after.isSymbolicLink() || before.ino !== after.ino || before.size !== after.size || before.mtimeMs !== after.mtimeMs) throw new Error('Settings changed during read; reload');
      const raw = buffer.subarray(0, length);
      file = { ...file, sha256: hash(raw) };
      const parsed: unknown = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(raw));
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('Settings root must be an object');
      const record = parsed as Record<string, unknown>;
      if (record.version !== 1) throw new Error('Unsupported settings version; expected 1');
      if (!record.settings || typeof record.settings !== 'object' || Array.isArray(record.settings)) throw new Error('settings must be an object');
      if (Object.keys(record.settings).length > 100) throw new Error('Too many settings entries');
      return { file, values: record.settings };
    } catch (error) { return { file: { ...file, issues: [(error as Error).message] }, values: {} }; }
  }

  async read(workspaceRoot: string | null): Promise<ConfigurationState> {
    const [user, workspace] = await Promise.all([this.readLayer('user', workspaceRoot), this.readLayer('workspace', workspaceRoot)]);
    const store = new ConfigurationStore(DESKTOP_SCHEMAS);
    const userIssues = [...user.file.issues, ...store.load('user', user.values)];
    const workspaceIssues = [...workspace.file.issues, ...store.load('workspace', workspace.values)];
    return {
      effective: store.effective(),
      user: { ...user.file, values: store.layer('user'), issues: userIssues },
      workspace: { ...workspace.file, values: store.layer('workspace'), issues: workspaceIssues },
    };
  }

  update(workspaceRoot: string | null, scope: unknown, updates: unknown, expectedSha256: unknown): Promise<ConfigurationState> {
    const work = this.queue.catch(() => {}).then(async () => {
      if (scope !== 'user' && scope !== 'workspace') throw new Error('Invalid settings scope');
      if (scope === 'workspace' && !workspaceRoot) throw new Error('Open a workspace first');
      if (!updates || typeof updates !== 'object' || Array.isArray(updates) || Object.keys(updates).length > 100 || Object.keys(updates).some(key => key.length > 128)) throw new Error('Invalid settings update');
      if (expectedSha256 !== null && (typeof expectedSha256 !== 'string' || !/^[a-f0-9]{64}$/.test(expectedSha256))) throw new Error('Invalid settings version');
      const state = await this.read(workspaceRoot);
      const current = state[scope];
      if (current.issues.length) throw new Error(`Settings file has invalid entries; correct it before saving: ${current.issues.join('; ')}`);
      if (current.sha256 !== expectedSha256) throw new Error('Settings changed externally; reload before saving');
      if (!Object.keys(updates).length) return state;
      const store = new ConfigurationStore(DESKTOP_SCHEMAS);
      const issues = store.load(scope, { ...current.values, ...updates });
      if (issues.length) throw new Error(`Invalid configuration: ${issues.join('; ')}`);
      await this.write(workspaceRoot, scope, store.layer(scope), expectedSha256 as string | null);
      return this.read(workspaceRoot);
    });
    this.queue = work;
    void work.catch(() => {});
    return work;
  }

  private async write(workspaceRoot: string | null, scope: ConfigurationScope, values: Readonly<Record<string, ConfigurationValue>>, expectedSha256: string | null): Promise<void> {
    const filename = await this.filename(scope, workspaceRoot, true);
    const raw = Buffer.from(`${JSON.stringify({ version: 1, settings: values }, null, 2)}\n`, 'utf8');
    if (raw.length > MAX_BYTES) throw new Error('Settings exceed the 64 KiB limit');
    const temporary = `${filename}.${randomUUID()}.tmp`;
    let handle: fs.FileHandle | undefined;
    try {
      handle = await fs.open(temporary, 'wx', 0o600);
      await handle.writeFile(raw);
      await handle.sync();
      await handle.close();
      handle = undefined;
      for (let attempt = 0; attempt < 4; attempt += 1) {
        // Conflict detection, not an OS-level atomic CAS against hostile writers.
        await this.filename(scope, workspaceRoot);
        const latest = await this.readLayer(scope, workspaceRoot);
        if (latest.file.issues.length || latest.file.sha256 !== expectedSha256) throw new Error('Settings changed during save; reload before saving');
        try { await fs.rename(temporary, filename); break; }
        catch (error) {
          if (!['EPERM', 'EBUSY', 'EACCES'].includes((error as NodeJS.ErrnoException).code || '') || attempt === 3) throw error;
          await new Promise(resolve => setTimeout(resolve, 25 * (2 ** attempt)));
        }
      }
    } finally {
      await handle?.close().catch(() => {});
      await fs.rm(temporary, { force: true });
    }
  }
}

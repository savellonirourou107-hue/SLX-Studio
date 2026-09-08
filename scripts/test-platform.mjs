import assert from 'node:assert/strict';
import { test } from 'node:test';
import * as fs from 'node:fs/promises';
import { once } from 'node:events';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
async function loadTypeScript(relative) {
  const result = await build({ entryPoints: [path.join(root, relative)], bundle: true, platform: 'node', format: 'esm', write: false });
  return import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`);
}
const { FrameDecoder, PythonBackend } = await loadTypeScript('apps/desktop/electron/backend.ts');
const { CommandRegistry } = await loadTypeScript('packages/commands/index.ts');
const { ConfigurationStore } = await loadTypeScript('packages/configuration/index.ts');
const { CustomEditorRegistry } = await loadTypeScript('packages/editor/registry.ts');
const { OutputService, ProblemsService, ViewRegistry } = await loadTypeScript('packages/workbench/index.ts');
const { ConfigurationFiles } = await loadTypeScript('apps/desktop/electron/configuration.ts');
const frame = value => {
  const payload = Buffer.from(JSON.stringify(value));
  return Buffer.concat([Buffer.from(`Content-Length: ${payload.length}\r\n\r\n`), payload]);
};

test('frame decoder handles split/coalesced frames and Unicode byte lengths', () => {
  const decoder = new FrameDecoder();
  const values = [{ id: 1, result: '控制工程' }, { id: 2, result: [1, 2, 3] }];
  const bytes = Buffer.concat(values.map(frame));
  const found = [];
  for (const byte of bytes) found.push(...decoder.feed(Buffer.from([byte])));
  assert.deepEqual(found, values);
  assert.deepEqual(new FrameDecoder().feed(bytes), values);
});

test('frame decoder rejects malformed, oversized and non-UTF8 responses', () => {
  for (const bytes of [
    Buffer.from('Content-Length: 2\r\nContent-Length: 2\r\n\r\n{}'),
    Buffer.from('Content-Length: 999999999\r\n\r\n'),
    Buffer.from('Content-Length: 0\r\n\r\n'),
    Buffer.alloc(4097, 65),
    Buffer.from('Content-Length: 1\r\n\r\nx'),
    Buffer.concat([Buffer.from('Content-Length: 1\r\n\r\n'), Buffer.from([255])]),
  ]) assert.throws(() => new FrameDecoder().feed(bytes));
});

test('command registry validates, shares handlers, checks enablement and disposes', async () => {
  const registry = new CommandRegistry();
  let called = 0;
  const definition = { id: 'file.save', title: 'File: Save', run: () => called++ };
  const dispose = registry.register(definition);
  definition.run = () => { throw new Error('mutated original'); };
  await registry.execute('file.save');
  assert.equal(called, 1);
  assert.throws(() => registry.register({ id: 'file.save', title: 'duplicate', run() {} }));
  for (const id of ['', 'file..save', 'file.', '.save', '../save']) assert.throws(() => registry.register({ id, title: 'Invalid', run() {} }));
  assert.throws(() => registry.register({ id: 'file.bad', title: '', run() {} }));
  registry.register({ id: 'file.disabled', title: 'Disabled', enabled: () => false, run() { throw new Error('must not execute'); } });
  await assert.rejects(registry.execute('file.disabled'), /unavailable/);
  dispose();
  dispose();
  await assert.rejects(registry.execute('file.save'), /Unknown command/);
});

test('configuration uses default < user < workspace precedence and rejects unsafe workspace overrides', () => {
  const store = new ConfigurationStore([]);
  const dispose = store.register({ key: 'editor.fontSize', defaultValue: 14, validate: value => typeof value === 'number', workspaceWritable: true });
  store.register({ key: 'runtime.python', defaultValue: 'python', validate: value => typeof value === 'string', sensitive: true });
  store.register({ key: 'editor.optional', defaultValue: 'fallback', validate: value => value === null || typeof value === 'string' });
  store.setUser('editor.optional', null);
  assert.equal(store.get('editor.optional'), null, 'explicit null is not mistaken for a missing setting');
  assert.equal(store.get('editor.fontSize'), 14);
  store.setUser('editor.fontSize', 16);
  store.setWorkspace('editor.fontSize', 18);
  assert.equal(store.get('editor.fontSize'), 18);
  store.clearWorkspace('editor.fontSize');
  assert.equal(store.get('editor.fontSize'), 16);
  assert.throws(() => store.setWorkspace('runtime.python', 'evil'), /not workspace-writable/);
  assert.throws(() => store.setUser('editor.fontSize', 'large'), /Invalid value/);
  assert.throws(() => store.register({ key: 'editor.fontSize', defaultValue: 20, validate: value => typeof value === 'number' }));
  assert.deepEqual(store.load('user', { 'editor.fontSize': 19, unknown: true }), ['unknown: Unknown configuration: unknown']);
  assert.equal(store.get('editor.fontSize'), 19);
  assert.deepEqual(store.layer('user'), { 'editor.fontSize': 19 });
  assert.deepEqual(store.load('workspace', { 'editor.fontSize': 'large', 'runtime.python': 'evil' }), ['editor.fontSize: invalid value', 'runtime.python: not workspace-writable']);
  assert.equal(store.get('editor.fontSize'), 19);
  assert.deepEqual(store.layer('workspace'), {});
  assert.deepEqual(store.load('workspace', null), ['settings must be an object']);
  dispose();
  assert.throws(() => store.get('editor.fontSize'), /Unknown/);
});

test('Workbench views, custom editors, output and problems are bounded and disposable', () => {
  const views = new ViewRegistry();
  const disposeView = views.register({ id: 'panel.output', title: 'Output', location: 'panel' });
  assert.throws(() => views.register({ id: 'panel.output', title: 'Duplicate', location: 'panel' }));
  disposeView();
  assert.equal(views.list().length, 0);
  const editors = new CustomEditorRegistry();
  const disposeEditor = editors.register({ id: 'editor.slx', label: 'SLX', extensions: ['.slx'], priority: 10, open() {} });
  assert.equal(editors.resolve('folder/model.SLX')?.id, 'editor.slx');
  assert.throws(() => editors.register({ id: 'editor.bad', label: 'bad', extensions: ['slx'], open() {} }));
  disposeEditor();
  assert.equal(editors.resolve('model.slx'), undefined);
  const output = new OutputService(2, 20);
  let outputEvents = 0;
  const unsubscribe = output.subscribe(() => outputEvents++);
  output.append('1234567890'); output.append('abcdefghij'); output.append('overflow');
  assert.equal(output.snapshot().length, 2);
  output.append('x'.repeat(100));
  assert.ok(output.snapshot().every(entry => entry.text.length <= 20));
  assert.equal(outputEvents, 4);
  unsubscribe(); output.append('ignored event');
  assert.equal(outputEvents, 4);
  const problems = new ProblemsService(1);
  problems.replace([{ path: 'a.m', message: 'warning', severity: 'warning' }, { path: 'b.m', message: 'error', severity: 'error' }]);
  assert.deepEqual(problems.snapshot().map(problem => problem.path), ['a.m']);
  assert.throws(() => problems.replace([{ path: '', message: 'bad', severity: 'error' }]));
});

test('configuration files persist safe layers and fail closed on conflicts or malformed input', async () => {
  const fixture = await fs.mkdtemp(path.join(os.tmpdir(), 'slx-settings-'));
  const workspace = path.join(fixture, 'workspace');
  await fs.mkdir(workspace);
  const files = new ConfigurationFiles(path.join(fixture, 'state'));
  try {
    let state = await files.read(workspace);
    assert.equal(state.effective['editor.fontSize'], 14);
    assert.equal(state.user.exists, false);
    state = await files.update(workspace, 'user', { 'editor.fontSize': 16 }, null);
    assert.equal(state.effective['editor.fontSize'], 16);
    state = await files.update(workspace, 'workspace', { 'editor.minimap': true }, null);
    assert.equal(state.effective['editor.minimap'], true);
    assert.match(await fs.readFile(path.join(workspace, '.slx-studio', 'settings.json'), 'utf8'), /"editor\.minimap": true/);
    const beforeConflict = await files.read(workspace);
    await fs.writeFile(path.join(fixture, 'state', 'settings.json'), '{"version":1,"settings":{"editor.fontSize":20}}');
    await assert.rejects(files.update(workspace, 'user', { 'editor.fontSize': 18 }, beforeConflict.user.sha256), /changed externally/);
    await assert.rejects(files.update(workspace, 'workspace', { 'matlab.path': 'evil' }, state.workspace.sha256), /Invalid configuration/);
    await fs.writeFile(path.join(workspace, '.slx-studio', 'settings.json'), '{broken');
    state = await files.read(workspace);
    assert.match(state.workspace.issues.join('\n'), /Unexpected|JSON/);
    assert.equal(state.effective['editor.minimap'], false, 'malformed workspace settings fall back to defaults');
    await assert.rejects(files.update(workspace, 'workspace', { 'editor.minimap': false }, state.workspace.sha256), /invalid entries/);
    if (process.platform === 'win32') {
      const target = path.join(fixture, 'outside');
      const linkedWorkspace = path.join(fixture, 'linked-workspace');
      await fs.mkdir(target);
      await fs.mkdir(linkedWorkspace);
      await fs.symlink(target, path.join(linkedWorkspace, '.slx-studio'), 'junction');
      await fs.writeFile(path.join(target, 'settings.json'), '{"version":1,"settings":{}}');
      const linked = await files.read(linkedWorkspace);
      assert.match(linked.workspace.issues.join('\n'), /link|junction/);
    }
  } finally { await fs.rm(fixture, { recursive: true, force: true }); }
});

test('configuration updates are bounded and concurrent versions cannot silently overwrite each other', async () => {
  const fixture = await fs.mkdtemp(path.join(os.tmpdir(), 'slx-settings-bounds-'));
  const files = new ConfigurationFiles(path.join(fixture, 'state'));
  try {
    await assert.rejects(files.update(null, 'workspace', { 'editor.fontSize': 18 }, null), /workspace/);
    await assert.rejects(files.update(fixture, '../outside', {}, null), /scope/);
    await assert.rejects(files.update(fixture, 'user', { 'editor.fontSize': 99 }, null), /invalid value/);
    const pending = [
      files.update(fixture, 'user', { 'editor.fontSize': 16 }, null),
      files.update(fixture, 'user', { 'editor.fontSize': 18 }, null),
    ];
    const results = await Promise.allSettled(pending);
    assert.equal(results[0].status, 'fulfilled');
    assert.equal(results[1].status, 'rejected');
    assert.match(results[1].reason.message, /changed externally/);
    assert.equal((await files.read(fixture)).effective['editor.fontSize'], 16);
    await fs.writeFile(path.join(fixture, 'state', 'settings.json'), Buffer.alloc(64 * 1024 + 1, 32));
    const bounded = await files.read(fixture);
    assert.match(bounded.user.issues.join('\n'), /64 KiB/);
    assert.equal(bounded.effective['editor.fontSize'], 14);
    assert.deepEqual((await fs.readdir(path.join(fixture, 'state'))).filter(name => name.endsWith('.tmp')), []);
  } finally { await fs.rm(fixture, { recursive: true, force: true }); }
});

test('real Python supervisor correlates requests, bounds pending work and never replays after close/crash', async () => {
  const fixture = await fs.mkdtemp(path.join(os.tmpdir(), 'slx-platform-'));
  const backend = new PythonBackend(process.env.SLX_STUDIO_PYTHON || 'python', fixture, root, path.join(fixture, 'state'));
  try {
    const jobs = Array.from({ length: 33 }, () => backend.request('initialize'));
    const results = await Promise.allSettled(jobs);
    assert.equal(results.filter(result => result.status === 'fulfilled').length, 32);
    assert.match(results[32].reason.message, /Too many pending/);
    assert.equal(results[0].value.matlab_started, false);
    await assert.rejects(backend.request('document/read', { relative: '../escape.m' }), /relative path/);
    assert.deepEqual((await backend.request('workspace/listDirectory')).items, []);
    // The private child is accessed only here to inject an owned-process crash.
    const exited = once(backend.child, 'exit');
    backend.child.kill();
    const pending = backend.request('initialize');
    await assert.rejects(pending, /exited|closed|EPIPE|write/i);
    await exited;
    await assert.rejects(backend.request('initialize'), /closed/);
  } finally {
    backend.close();
    await fs.rm(fixture, { recursive: true, force: true });
  }
});

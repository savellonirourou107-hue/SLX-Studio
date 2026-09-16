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
const { OutputService, ProblemsService, ViewRegistry, WorkbenchContributionRegistry } = await loadTypeScript('packages/workbench/index.ts');
const { endpoint, position, scene } = await loadTypeScript('packages/model/geometry.ts');
const { ConfigurationFiles } = await loadTypeScript('apps/desktop/electron/configuration.ts');
const { ExtensionHostManager } = await loadTypeScript('apps/desktop/electron/extensions.ts');
const { matlabSection } = await loadTypeScript('packages/editor/sections.ts');
const { MATLAB_CATALOG, MATLAB_SYMBOLS } = await loadTypeScript('packages/editor/matlab-catalog.ts');
const { extractMatlabSymbols, matlabCallContext, matlabCode, MatlabSymbolCache, MAX_SYMBOL_SOURCE_CHARS, MAX_LOCAL_SYMBOLS } = await loadTypeScript('packages/editor/matlab-language.ts');
const frame = value => {
  const payload = Buffer.from(JSON.stringify(value));
  return Buffer.concat([Buffer.from(`Content-Length: ${payload.length}\r\n\r\n`), payload]);
};

test('MATLAB offline catalog identifies products and includes real parameter signatures', () => {
  assert.equal(new Set(MATLAB_CATALOG.map(item => item.name)).size, MATLAB_CATALOG.length);
  for (const item of MATLAB_CATALOG) {
    assert.ok(item.documentation && item.signatures.length);
    for (const signature of item.signatures) for (const parameter of signature.parameters) assert.ok(signature.label.includes(parameter));
  }
  assert.equal(MATLAB_SYMBOLS.get('zeros').product, 'MATLAB');
  assert.equal(MATLAB_SYMBOLS.get('sim').product, 'Simulink');
  assert.equal(MATLAB_SYMBOLS.get('tf').product, 'Control System Toolbox');
  assert.equal(MATLAB_SYMBOLS.get('linearize').product, 'Simulink Control Design');
  assert.deepEqual(MATLAB_SYMBOLS.get('plot').signatures[0].parameters, ['X', 'Y']);
});

test('MATLAB lexical symbols ignore strings/comments and bound document/symbol counts', () => {
  const source = `% hidden = 1;\ntext = 'fake = 2';\n%{\nblocked = 3;\n%}\nKp = 2;\nfor i = 1:5\nend\nfunction [y, err] = local_fn(x, gain)\ny = x;\nend\nobj.field = 1;\n`;
  const symbols = extractMatlabSymbols(source);
  assert.deepEqual(new Set(symbols.map(item => item.name)), new Set(['text', 'Kp', 'i', 'y', 'err', 'local_fn', 'x', 'gain']));
  assert.equal(symbols.find(item => item.name === 'local_fn').kind, 'function');
  assert.equal(symbols.find(item => item.name === 'x').kind, 'parameter');
  assert.deepEqual(extractMatlabSymbols('x'.repeat(MAX_SYMBOL_SOURCE_CHARS + 1)), []);
  assert.equal(extractMatlabSymbols(Array.from({ length: 1500 }, (_, i) => `value${i} = 1;`).join('\n')).length, MAX_LOCAL_SYMBOLS);
  const astral = `message = '😀';\nreal_variable = 1;`;
  assert.equal(matlabCode(astral).code.length, astral.length);
  assert.ok(extractMatlabSymbols(astral).some(item => item.name === 'real_variable'));
  assert.ok(extractMatlabSymbols(`y = A'; z = 1;`).some(item => item.name === 'z'));
});

test('MATLAB signature context counts only immediate call arguments', () => {
  for (const [source, name, parameter] of [
    ['plot(', 'plot', 0], ['plot(x,', 'plot', 1],
    ['plot([1,2], tf([1], [1,2]),', 'plot', 2],
    ['plot(x, tf([1],', 'tf', 1],
    ["plot('a,b',", 'plot', 1], ["plot(x',", 'plot', 1],
    ['plot(x, ... comment\n', 'plot', 1],
    ['plot({1, 2},', 'plot', 1],
  ]) assert.deepEqual(matlabCallContext(source), { name, parameter });
  for (const source of ['plot(x)', '% plot(', "disp('plot(", 'obj.plot(', 'plot(]']) assert.equal(matlabCallContext(source), null);
});

test('MATLAB symbol cache debounces by version, avoids scans on reads, and releases listeners', async () => {
  class Model {
    text = 'first = 1;'; version = 1; reads = 0; changes = new Set(); disposals = new Set();
    getValue() { this.reads++; return this.text; }
    getValueLength() { return this.text.length; }
    getVersionId() { return this.version; }
    onDidChangeContent(fn) { this.changes.add(fn); return { dispose: () => this.changes.delete(fn) }; }
    onWillDispose(fn) { this.disposals.add(fn); return { dispose: () => this.disposals.delete(fn) }; }
    edit(text) { this.text = text; this.version++; for (const fn of this.changes) fn(); }
    dispose() { for (const fn of [...this.disposals]) fn(); }
  }
  const cache = new MatlabSymbolCache(20);
  const model = new Model();
  try {
    cache.track(model); cache.track(model);
    assert.equal(model.reads, 1);
    for (let i = 0; i < 20; i++) { model.edit(`value${i} = 2;`); cache.read(model); }
    assert.equal(model.reads, 1, 'typing and completions do not synchronously rescan');
    await new Promise(resolve => setTimeout(resolve, 60));
    assert.equal(model.reads, 2);
    assert.deepEqual(cache.read(model).map(item => item.name), ['value19']);
    for (const fn of model.changes) fn();
    await new Promise(resolve => setTimeout(resolve, 40));
    assert.equal(model.reads, 2, 'unchanged version is not scanned twice');
    model.edit('pending = 1;'); model.dispose();
    await new Promise(resolve => setTimeout(resolve, 40));
    assert.equal(model.reads, 2);
    assert.equal(model.changes.size + model.disposals.size + cache.size, 0);
    const large = new Model(); large.text = 'x'.repeat(MAX_SYMBOL_SOURCE_CHARS + 1);
    cache.track(large); assert.equal(large.reads, 0);
    for (let i = 0; i < 100; i++) { const item = new Model(); cache.track(item); item.dispose(); }
    assert.equal(cache.size, 1);
    large.dispose(); assert.equal(cache.size, 0);
  } finally { cache.dispose(); }
});

test('console chunks preserve non-newline output while retaining a bounded tail', () => {
  const output = new OutputService(3, 20);
  output.append('command'); output.appendChunk('first'); output.appendChunk('last');
  assert.deepEqual(output.snapshot().map(entry => entry.text), ['command', 'firstlast']);
  output.appendChunk('x'.repeat(30));
  assert.equal(output.snapshot().map(entry => entry.text).join(''), 'x'.repeat(20));
  output.append('done'); output.appendChunk('next');
  assert.equal(output.snapshot().at(-1).text, 'next');
});

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

test('MATLAB section selection preserves source line ranges and ignores block-comment markers', () => {
  const source = 'value = 1;\r\n%% First\r\nvalue = 2;\r\n%{\r\n%% not a section\r\n%}\r\n%% Second\r\nvalue = 3;';
  assert.deepEqual(matlabSection(source, 3), { code: '%% First\nvalue = 2;\n%{\n%% not a section\n%}', startLine: 2, endLine: 6 });
  assert.deepEqual(matlabSection(source, 7), { code: '%% Second\nvalue = 3;', startLine: 7, endLine: 8 });
  assert.deepEqual(matlabSection(source, 1), { code: 'value = 1;', startLine: 1, endLine: 1 });
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

test('Workbench contribution activation owns registrations and releases them on deactivate or failure', async () => {
  const registry = new WorkbenchContributionRegistry();
  const views = new ViewRegistry();
  const editors = new CustomEditorRegistry();
  let activated = 0;
  const dispose = registry.register({ id: 'builtin.test', activate(context) {
    activated += 1;
    context.add(views.register({ id: 'view.test', title: 'Test', location: 'panel' }));
    context.add(editors.register({ id: 'editor.test', label: 'Test', extensions: ['.m'], open() {} }));
  } });
  await registry.activate('builtin.test');
  assert.deepEqual(registry.list(), [{ id: 'builtin.test', state: 'active' }]);
  assert.equal(views.list().length, 1);
  registry.deactivate('builtin.test');
  assert.deepEqual(registry.list(), [{ id: 'builtin.test', state: 'inactive' }]);
  assert.equal(views.list().length, 0);
  assert.equal(editors.list().length, 0);
  await Promise.all([registry.activate('builtin.test'), registry.activate('builtin.test')]);
  assert.equal(activated, 2);
  const broken = registry.register({ id: 'builtin.broken', activate(context) { context.add(() => { throw new Error('dispose still attempted'); }); throw new Error('activation failed'); } });
  await assert.rejects(registry.activate('builtin.broken'), /activation failed/);
  assert.equal(registry.list().find(item => item.id === 'builtin.broken')?.state, 'failed');
  broken();
  dispose();
  assert.equal(registry.list().length, 0);
});

test('static model geometry rejects unsafe positions and keeps bounded topology visible', () => {
  assert.deepEqual(position('[10 20 50 60]'), { x: 10, y: 20, width: 40, height: 40 });
  assert.equal(position('[NaN 0 1 1]'), null);
  assert.equal(position('[0 0 10000001 10]'), null);
  assert.deepEqual(endpoint('Gain:out1'), { path: 'Gain', kind: 'out', port: 1 });
  assert.equal(endpoint('broken'), null);
  const block = (path, sid, rawPosition) => ({ system_id: 'root', sid, name: path, block_type: 'Gain', path, parameters: { Position: rawPosition } });
  const result = scene([block('Input', '1', '[10 40 60 80]'), block('Gain', '2', '[120 40 170 80]')], [{ system_id: 'root', src: 'Input:out1', dst: 'Gain:in1', name: '' }]);
  assert.equal(result.nodes.length, 2);
  assert.equal(result.wires.length, 1);
  assert.equal(result.unresolved, 0);
  assert.match(result.wires[0].path, /^M /);
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

test('trusted extension host is lazy, validates manifests, and releases its process', async () => {
  const fixture = await fs.mkdtemp(path.join(os.tmpdir(), 'slx-extensions-'));
  const trusted = path.join(fixture, 'trusted.ext');
  await fs.mkdir(trusted);
  await fs.writeFile(path.join(trusted, 'slx-extension.json'), JSON.stringify({
    id: 'trusted.ext', apiVersion: 1, version: '1.0.0', main: 'extension.mjs', activationEvents: ['onCommand:trusted.hello'],
    contributes: { commands: [{ command: 'trusted.hello', title: 'Trusted Hello' }], views: [{ id: 'trusted.view', title: 'Trusted View', location: 'sidebar' }], editors: [{ id: 'trusted.editor', label: 'Trusted Editor', extensions: ['.trusted'] }] },
  }));
  await fs.writeFile(path.join(trusted, 'extension.mjs'), "export function activate(){return {}}; export function execute(command,args){return {command,args}}; export function deactivate(){};");
  const incompatible = path.join(fixture, 'bad.ext');
  await fs.mkdir(incompatible);
  await fs.writeFile(path.join(incompatible, 'slx-extension.json'), JSON.stringify({ id: 'bad.ext', apiVersion: 99, version: '1.0.0', main: 'extension.mjs' }));
  await fs.writeFile(path.join(incompatible, 'extension.mjs'), 'export function activate(){};');
  const throwing = path.join(fixture, 'throw.ext');
  await fs.mkdir(throwing);
  await fs.writeFile(path.join(throwing, 'slx-extension.json'), JSON.stringify({ id: 'throw.ext', apiVersion: 1, version: '1.0.0', main: 'extension.mjs', contributes: {} }));
  await fs.writeFile(path.join(throwing, 'extension.mjs'), "export function activate(){throw new Error('extension boom')};");
  const manager = new ExtensionHostManager(fixture);
  try {
    const discovered = await manager.discover();
    assert.equal(discovered.find(item => item.id === 'trusted.ext')?.state, 'inactive');
    assert.equal(discovered.find(item => item.id === 'bad.ext')?.state, 'failed');
    assert.equal(manager.list().find(item => item.id === 'trusted.ext')?.state, 'inactive');
    await assert.rejects(manager.activate('bad.ext'), /unsupported extension API version/);
    await assert.rejects(manager.activate('throw.ext'), /extension boom/);
    assert.equal(manager.list().find(item => item.id === 'throw.ext')?.state, 'failed');
    const active = await manager.activate('trusted.ext');
    assert.equal(active.state, 'active');
    const concurrent = await Promise.all([manager.activate('trusted.ext'), manager.activate('trusted.ext')]);
    assert.ok(concurrent.every(item => item.state === 'active'));
    assert.equal(manager.children.size, 1);
    assert.equal((await manager.discover()).find(item => item.id === 'trusted.ext').state, 'active', 'listing cannot reset a live extension');
    assert.deepEqual(await manager.execute('trusted.ext', 'trusted.hello', { value: 3 }), { command: 'trusted.hello', args: { value: 3 } });
    await manager.deactivate('trusted.ext');
    assert.equal(manager.list().find(item => item.id === 'trusted.ext')?.state, 'inactive');
  } finally { await manager.close(); await fs.rm(fixture, { recursive: true, force: true }); }
});

test('extension failures are isolated, hangs terminate, and restart is explicit', { timeout: 20_000 }, async () => {
  const fixture = await fs.mkdtemp(path.join(os.tmpdir(), 'slx-extension-faults-'));
  const states = [];
  async function extension(id, source, main = 'extension.mjs') {
    await fs.mkdir(path.join(fixture, id), { recursive: true });
    await fs.writeFile(path.join(fixture, id, 'slx-extension.json'), JSON.stringify({ id, apiVersion: 1, version: '1.0.0', main, contributes: { commands: [{ command: `${id}.run`, title: id }] } }));
    await fs.writeFile(path.join(fixture, id, 'extension.mjs'), source);
  }
  await extension('good.ext', 'export async function execute(){await new Promise(r=>setTimeout(r,250));return "good"}');
  await extension('crash.ext', 'export function execute(){setTimeout(()=>process.exit(23),30);return new Promise(()=>{})}');
  await extension('hung.ext', 'export function execute(){while(true){}}');
  await extension('escape.ext', 'export function execute(){}', '../good.ext/extension.mjs');
  await extension('link.ext', 'export function execute(){}', 'nested/extension.mjs');
  await fs.symlink(path.join(fixture, 'good.ext'), path.join(fixture, 'link.ext/nested'), process.platform === 'win32' ? 'junction' : 'dir');
  const manager = new ExtensionHostManager(fixture, state => states.push(state));
  try {
    await manager.discover();
    await assert.rejects(manager.activate('escape.ext'), /relative path|escapes/);
    await assert.rejects(manager.activate('link.ext'), /link|reparse/);
    await Promise.all([manager.activate('good.ext'), manager.activate('good.ext'), manager.activate('crash.ext'), manager.activate('hung.ext')]);
    assert.equal(manager.children.size, 3, 'concurrent activation owns one child per extension');
    const good = manager.execute('good.ext', 'good.ext.run');
    await assert.rejects(manager.execute('crash.ext', 'crash.ext.run'), /exited/);
    assert.equal(await good, 'good', 'one child exiting cannot reject another child\'s request');
    await assert.rejects(manager.execute('hung.ext', 'hung.ext.run'), /timed out/);
    assert.equal(manager.list().find(item => item.id === 'hung.ext').state, 'failed');
    assert.equal((await manager.discover()).find(item => item.id === 'hung.ext').state, 'failed');
    await fs.writeFile(path.join(fixture, 'hung.ext/extension.mjs'), 'export function execute(){return "restarted"}');
    await manager.restart('hung.ext');
    assert.equal(await manager.execute('hung.ext', 'hung.ext.run'), 'restarted');
    assert.ok(states.some(item => item.id === 'hung.ext' && item.state === 'failed'));
    assert.equal(await manager.execute('good.ext', 'good.ext.run'), 'good');
  } finally { await manager.close(); await fs.rm(fixture, { recursive: true, force: true }); }
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

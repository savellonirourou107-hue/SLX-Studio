// Controlled DOM/service contracts. Real Electron coverage is in test-desktop.mjs.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { build } from 'esbuild';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const bundle = await build({ entryPoints: [path.join(root, 'apps/desktop/renderer/file-creation.ts')], bundle: true, platform: 'node', format: 'esm', write: false });
const { FileCreationController } = await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`);
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
class Element extends EventTarget {
  value = ''; textContent = ''; disabled = false; open = false; attributes = {};
  setAttribute(name, value) { this.attributes[name] = value; }
  showModal() { this.open = true; }
  close() { this.open = false; this.dispatchEvent(new Event('close')); }
  focus() {} select() {}
}
function fixture(overrides = {}) {
  const ui = Object.fromEntries(['dialog', 'form', 'input', 'title', 'help', 'status', 'submit', 'cancel'].map(key => [key, new Element()]));
  const creates = [], opened = [], logs = [], refreshed = [];
  let source = { path: '实验/控制.m', content: '%% 控制\r\nKp = 8;', bom: true };
  const controller = new FileCreationController(ui, { create: async (...args) => { creates.push(args); return overrides.create ? overrides.create(...args) : { path: args[1], content: args[2], warnings: [] }; } },
    () => ({ ...source }), overrides.isOpenPath || (() => false),
    async file => { opened.push(file); if (overrides.open) await overrides.open(file); },
    async () => { refreshed.push(true); if (overrides.refresh) await overrides.refresh(); }, text => logs.push(text));
  controller.setWorkspace('/workspace');
  return { controller, ui, creates, opened, logs, refreshed, changeSource: value => { source = { ...source, content: value }; } };
}

test('new file requires a workspace and never writes merely by opening its dialog', () => {
  const f = fixture(); f.controller.setWorkspace(null);
  assert.throws(() => f.controller.show('new'), /workspace/);
  f.controller.setWorkspace('/workspace'); f.controller.show('new');
  assert.equal(f.ui.input.value, 'untitled.m'); assert.deepEqual(f.creates, []);
  assert.throws(() => f.controller.show('copy'), /Finish or cancel/);
});

test('cancel button and Escape have no filesystem effects', () => {
  for (const method of ['button', 'escape']) {
    const f = fixture(); f.controller.show('new');
    if (method === 'button') f.ui.cancel.dispatchEvent(new Event('click'));
    else f.ui.dialog.dispatchEvent(new Event('cancel', { cancelable: true }));
    assert.equal(f.controller.active, false); assert.deepEqual(f.creates, []);
  }
});

test('new file publishes empty UTF-8 through the scoped service and opens it', async () => {
  const f = fixture(); f.controller.show('new'); f.ui.input.value = '实验\\new.m';
  await f.controller.submit();
  assert.deepEqual(f.creates, [['/workspace', '实验/new.m', '', false]]);
  assert.deepEqual(f.opened, ['实验/new.m']); assert.equal(f.refreshed.length, 1);
  assert.equal(f.controller.active, false);
});

test('copy uses the captured buffer/BOM rather than later input or a saved disk file', async () => {
  const f = fixture(); f.controller.show('copy');
  assert.equal(f.ui.input.value, '实验/控制-copy.m');
  f.changeSource('later typing');
  await f.controller.submit();
  assert.deepEqual(f.creates, [['/workspace', '实验/控制-copy.m', '%% 控制\r\nKp = 8;', true]]);
  assert.ok(f.logs.some(line => line.includes('source remains unchanged')));
});

test('blank, oversized, ambiguous and non-MATLAB input cannot submit', async () => {
  for (const name of ['', 'a.slx', 'a.m ', ' a.m', 'a'.repeat(4097) + '.m']) {
    const f = fixture(); f.controller.show('new'); f.ui.input.value = name;
    await f.controller.submit(); assert.deepEqual(f.creates, []);
    assert.match(f.ui.status.textContent, /workspace-relative/);
    assert.equal(f.ui.dialog.open, true);
  }
});

test('an open target buffer blocks creation even if the disk target was deleted', async () => {
  const f = fixture({ isOpenPath: () => true }); f.controller.show('new');
  await f.controller.submit(); assert.deepEqual(f.creates, []);
  assert.match(f.ui.status.textContent, /open editor/);
});

test('pending creation disables input, cannot be canceled, and coalesces double submit', async () => {
  const io = deferred(); const f = fixture({ create: () => io.promise }); f.controller.show('new');
  const job = f.controller.submit(); await f.controller.submit();
  assert.equal(f.creates.length, 1); assert.equal(f.controller.busy, true);
  assert.equal(f.ui.input.disabled, true); assert.equal(f.ui.submit.disabled, true);
  assert.equal(f.controller.cancel(), false); assert.equal(f.ui.dialog.open, true);
  io.resolve({ path: 'untitled.m', warnings: [] }); await job;
  assert.equal(f.controller.busy, false); assert.equal(f.ui.submit.disabled, false);
});

test('a failed write remains visible and is never retried without a new submit', async () => {
  const f = fixture({ create: async () => { throw new Error('destination exists'); } });
  f.controller.show('new'); await f.controller.submit();
  assert.equal(f.creates.length, 1); assert.equal(f.ui.dialog.open, true);
  assert.match(f.ui.status.textContent, /destination exists/); assert.deepEqual(f.opened, []);
  assert.equal(f.ui.submit.disabled, false);
});

test('workspace change invalidates an unsubmitted dialog', async () => {
  const f = fixture(); f.controller.show('copy'); f.controller.setWorkspace('/other');
  await f.controller.submit(); assert.deepEqual(f.creates, []); assert.equal(f.controller.active, false);
});

test('late completion never opens a file in another workspace', async () => {
  const io = deferred(); const f = fixture({ create: () => io.promise }); f.controller.show('new');
  const job = f.controller.submit(); f.controller.setWorkspace('/other');
  io.resolve({ path: 'untitled.m', warnings: [] }); await job;
  assert.deepEqual(f.opened, []); assert.deepEqual(f.refreshed, []);
  assert.ok(f.logs.some(line => line.includes('previous workspace')));
});

test('workspace change during refresh also rejects a stale editor open', async () => {
  const io = deferred(); const f = fixture({ refresh: () => io.promise }); f.controller.show('new');
  const job = f.controller.submit(); await new Promise(resolve => setImmediate(resolve));
  f.controller.setWorkspace('/other'); io.resolve(); await job;
  assert.deepEqual(f.opened, []);
});

test('successful publication remains success when opening or refresh fails', async () => {
  const f = fixture({ open: async () => { throw new Error('file removed'); }, refresh: async () => { throw new Error('index unavailable'); } });
  f.controller.show('new'); await f.controller.submit(); await f.controller.submit();
  assert.equal(f.creates.length, 1); assert.equal(f.controller.active, false);
  assert.ok(f.logs.some(line => line.includes('could not open')));
  assert.ok(f.logs.some(line => line.includes('Explorer refresh failed')));
});

test('post-publication cleanup warnings are visible without retrying the write', async () => {
  const f = fixture({ create: async () => ({ path: 'untitled.m', warnings: ['cleanup failed'] }) });
  f.controller.show('new'); await f.controller.submit();
  assert.ok(f.logs.includes('cleanup failed')); assert.equal(f.creates.length, 1);
});

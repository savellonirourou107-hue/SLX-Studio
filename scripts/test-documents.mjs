// Deterministic document lifecycle contracts with a controlled editor/IO double.
// Real Monaco undo/redo and desktop integration remain in test-desktop.mjs.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { setImmediate as nextTurn } from 'node:timers/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { build } from 'esbuild';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const bundle = await build({
  entryPoints: [path.join(root, 'packages/editor/documents.ts')], bundle: true,
  platform: 'node', format: 'esm', write: false, external: ['./monaco'],
});
const { DocumentEditors } = await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`);
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const snapshot = (file = 'control.m', content = 'gain = 1;\n', extra = {}) => ({
  path: file, content, sha256: `${file}:${content}`, bom: false, eol: 'LF',
  mixed_eol: false, bytes: Buffer.byteLength(content), mtime_ns: 1, ...extra,
});

// This models only the public methods DocumentEditors uses, not MATLAB or Monaco.
class TextModel {
  constructor(content) { this.content = content; this.version = 1; this.alternative = 1; }
  listeners = new Set();
  disposed = false;
  stops = 0;
  getValue() { assert.equal(this.disposed, false); return this.content; }
  getVersionId() { return this.version; }
  getAlternativeVersionId() { return this.alternative; }
  pushStackElement() { this.stops += 1; }
  setValue(content) { this.content = content; this.alternative = ++this.version; for (const fn of this.listeners) fn(); }
  setEOL(eol) {
    const content = this.content.replace(/\r\n|\r|\n/g, eol === 1 ? '\r\n' : '\n');
    if (content !== this.content) this.setValue(content);
  }
  getLineCount() { return this.content.split('\n').length; }
  onDidChangeContent(fn) { this.listeners.add(fn); return { dispose: () => this.listeners.delete(fn) }; }
  isDisposed() { return this.disposed; }
  dispose() { assert.equal(this.disposed, false, 'a model is disposed only once'); this.disposed = true; this.listeners.clear(); }
}

function fixture(t, overrides = {}, choose = async () => 'Cancel') {
  const writes = [], drafts = new Map(), logs = [], models = [];
  const files = {
    read: async file => snapshot(file),
    draft: async file => drafts.get(file),
    save: async (base, content) => { writes.push({ base, content }); return snapshot(base.path, content); },
    keepDraft: async draft => { drafts.set(draft.path, draft); },
    clearDraft: async file => { drafts.delete(file); },
    ...overrides,
  };
  const editors = new DocumentEditors({ hidden: true }, files, choose, () => {}, text => logs.push(text));
  const view = {
    options: {}, model: null, setModel(model) { this.model = model; },
    updateOptions(options) { Object.assign(this.options, options); },
    saveViewState() { return null; }, restoreViewState() {}, layout() {}, focus() {},
  };
  // Inject a test-only runtime via ordinary TS-private properties. Production
  // does not expose any test hook or bypass its sandbox/typed filesystem service.
  editors.monaco = {
    Uri: { from: value => value },
    editor: { EndOfLineSequence: { LF: 0, CRLF: 1 }, createModel(content) { const model = new TextModel(content); models.push(model); return model; } },
  };
  editors.editor = view;
  editors.ensureEditor = async () => {};
  t.after(() => {
    for (const doc of editors.documents.values()) { clearTimeout(doc.timer); doc.listener.dispose(); }
    for (const model of models) if (!model.isDisposed()) model.dispose();
  });
  return { editors, files, writes, drafts, logs, models, view };
}

async function dirtyFile(f, file = 'control.m', content = 'gain = 2;\n') {
  await f.editors.open(file);
  const doc = f.editors.documents.get(file);
  doc.model.setValue(content);
  return doc;
}

test('save establishes an undo stop and only marks the written version clean', async t => {
  const io = deferred();
  const f = fixture(t, { save: () => io.promise });
  const doc = await dirtyFile(f);
  const savedVersion = doc.model.getAlternativeVersionId();
  const save = f.editors.save();
  await nextTurn();
  assert.equal(doc.model.stops, 1, 'saving must split the undo history before IO');
  doc.model.setValue('newer = 3;\n');
  io.resolve(snapshot('control.m', 'gain = 2;\n'));
  await save;
  assert.equal(doc.cleanAlternativeVersionId, savedVersion);
  assert.equal(f.editors.dirty(doc), true);
  assert.equal(f.drafts.get(doc.path).content, 'newer = 3;\n');
  assert.equal(f.drafts.get(doc.path).base.content, 'gain = 2;\n');
});

test('dirty tracking does not read or compare complete document contents', async t => {
  const f = fixture(t);
  await f.editors.open('control.m');
  const doc = f.editors.active;
  const getValue = doc.model.getValue;
  doc.model.getValue = () => { throw new Error('unexpected full-document read'); };
  assert.equal(f.editors.dirty(doc), false);
  doc.model.alternative += 1;
  assert.equal(f.editors.dirty(doc), true);
  doc.model.getValue = getValue;
});

test('concurrent saves use the latest acknowledged base rather than racing writes', async t => {
  const io = deferred();
  const calls = [];
  const f = fixture(t, { save: async (base, content) => {
    calls.push({ base, content });
    if (calls.length === 1) await io.promise;
    return snapshot(base.path, content);
  } });
  const doc = await dirtyFile(f);
  const first = f.editors.save();
  await nextTurn();
  doc.model.setValue('gain = 3;\n');
  const second = f.editors.save();
  await nextTurn();
  assert.equal(calls.length, 1);
  io.resolve();
  await Promise.all([first, second]);
  assert.equal(calls[1].base.sha256, snapshot(doc.path, 'gain = 2;\n').sha256);
  assert.equal(calls[1].content, 'gain = 3;\n');
  assert.equal(f.editors.dirty(doc), false);
});

test('failed saves preserve base and dirty contents, with no automatic write replay', async t => {
  let calls = 0;
  const f = fixture(t, { save: async () => { calls += 1; throw new Error('conflict'); } });
  const doc = await dirtyFile(f);
  const base = doc.base;
  await assert.rejects(f.editors.save(), /conflict/);
  await nextTurn();
  assert.equal(calls, 1);
  assert.equal(doc.base, base);
  assert.equal(doc.model.getValue(), 'gain = 2;\n');
  assert.equal(f.editors.dirty(doc), true);
  f.files.save = async (old, content) => snapshot(old.path, content);
  await f.editors.save();
  assert.equal(f.editors.dirty(doc), false, 'a later explicit save recovers the queue');
});

test('Save All includes inactive documents and skips clean files', async t => {
  const f = fixture(t);
  const a = await dirtyFile(f, 'a.m', 'a = 2;');
  const b = await dirtyFile(f, 'b.m', 'b = 3;');
  await f.editors.open('clean.m');
  await f.editors.saveAll();
  assert.deepEqual(f.writes.map(write => write.base.path), ['a.m', 'b.m']);
  assert.equal(f.editors.dirty(a) || f.editors.dirty(b), false);
  assert.equal(f.editors.active.path, 'clean.m', 'saving does not change focus');
});

test('Save All stops on a conflict and leaves subsequent files and drafts intact', async t => {
  const calls = [];
  const f = fixture(t, { save: async (base, content) => {
    calls.push(base.path);
    if (base.path === 'b.m') throw new Error('external modification');
    return snapshot(base.path, content);
  } });
  await dirtyFile(f, 'a.m');
  const b = await dirtyFile(f, 'b.m');
  const c = await dirtyFile(f, 'c.m');
  await f.editors.persistDraft(c);
  await assert.rejects(f.editors.saveAll(), /external modification/);
  assert.deepEqual(calls, ['a.m', 'b.m']);
  assert.equal(f.editors.dirty(b) && f.editors.dirty(c), true);
  assert.ok(f.drafts.has('c.m'));
});

test('mixed line endings remain protected from save and Save All', async t => {
  const f = fixture(t, { read: async file => snapshot(file, 'a\r\nb\n', { mixed_eol: true }) });
  await dirtyFile(f);
  await assert.rejects(f.editors.saveAll(), /Mixed line endings/);
  assert.equal(f.writes.length, 0);
});

test('late reload cannot overwrite typing while a disk read is pending', async t => {
  const f = fixture(t);
  await f.editors.open('control.m');
  const doc = f.editors.active, base = doc.base, io = deferred();
  f.files.read = () => io.promise;
  const reload = f.editors.reload();
  await nextTurn();
  doc.model.setValue('user = 99;');
  io.resolve(snapshot(doc.path, 'external = 1;'));
  await reload;
  assert.equal(doc.model.getValue(), 'user = 99;');
  assert.equal(doc.base, base);
  assert.ok(f.logs.some(line => line.includes('Reload canceled')));
});

test('reload confirmation does not authorize discarding edits made after its prompt', async t => {
  const answer = deferred();
  const f = fixture(t, {}, () => answer.promise);
  const doc = await dirtyFile(f);
  const reload = f.editors.reload();
  await nextTurn();
  doc.model.setValue('new = 7;');
  answer.resolve('Reload');
  await reload;
  assert.equal(doc.model.getValue(), 'new = 7;');
  assert.equal(f.editors.dirty(doc), true);
});

test('reload preserves another selected document\'s read-only policy', async t => {
  const f = fixture(t);
  await f.editors.open('a.m');
  await f.editors.open('b.m');
  f.editors.select('a.m');
  const io = deferred();
  f.files.read = () => io.promise;
  const reload = f.editors.reload();
  await nextTurn();
  f.editors.select('b.m');
  io.resolve(snapshot('a.m', 'a\r\nb\n', { mixed_eol: true }));
  await reload;
  assert.equal(f.view.options.readOnly, false);
  f.editors.select('a.m');
  assert.equal(f.view.options.readOnly, true);
});

test('reload waits for a save and cannot replace its base while that write is pending', async t => {
  const write = deferred();
  let read = false;
  const f = fixture(t, { save: () => write.promise });
  const doc = await dirtyFile(f);
  f.files.read = async file => { read = true; return snapshot(file, 'gain = 2;\n'); };
  const saving = f.editors.save();
  const reloading = f.editors.reload();
  await nextTurn();
  assert.equal(read, false);
  write.resolve(snapshot(doc.path, 'gain = 2;\n'));
  await Promise.all([saving, reloading]);
  assert.equal(read, true);
  assert.equal(f.editors.dirty(doc), false);
});

test('save queued behind reload cannot write the stale pre-reload snapshot', async t => {
  const io = deferred();
  const f = fixture(t, {}, async () => 'Reload');
  const doc = await dirtyFile(f);
  f.files.read = () => io.promise;
  const reload = f.editors.reload();
  const save = f.editors.save();
  await nextTurn();
  io.resolve(snapshot(doc.path, 'disk = 4;'));
  await Promise.all([reload, save]);
  assert.equal(f.writes.length, 0);
  assert.equal(doc.model.getValue(), 'disk = 4;');
});

test('dismissed or unknown close decisions never discard a dirty document', async t => {
  for (const answer of ['Cancel', '', 'unexpected']) {
    const f = fixture(t, {}, async () => answer);
    const doc = await dirtyFile(f);
    assert.equal(await f.editors.close(doc.path), false);
    assert.equal(doc.model.isDisposed(), false);
  }
});

test('concurrent closes share one decision and dispose exactly once', async t => {
  const answer = deferred();
  let prompts = 0;
  const f = fixture(t, {}, () => { prompts += 1; return answer.promise; });
  const doc = await dirtyFile(f);
  const one = f.editors.close(doc.path), two = f.editors.close(doc.path);
  await nextTurn();
  assert.equal(prompts, 1);
  answer.resolve('Discard');
  assert.deepEqual(await Promise.all([one, two]), [true, true]);
  assert.equal(doc.model.isDisposed(), true);
  assert.equal(f.editors.documents.size, 0);
});

test('editing during a Discard prompt cancels closing rather than discarding unseen edits', async t => {
  const answer = deferred();
  const f = fixture(t, {}, () => answer.promise);
  const doc = await dirtyFile(f);
  const closing = f.editors.close(doc.path);
  await nextTurn();
  doc.model.setValue('later = 3;');
  answer.resolve('Discard');
  assert.equal(await closing, false);
  assert.equal(doc.model.getValue(), 'later = 3;');
});

test('typing while close clears a draft keeps the editor and persists the newer draft', async t => {
  const io = deferred();
  const f = fixture(t);
  await f.editors.open('control.m');
  const doc = f.editors.active;
  f.files.clearDraft = () => io.promise;
  const closing = f.editors.close(doc.path);
  await nextTurn();
  doc.model.setValue('new = 5;');
  io.resolve();
  assert.equal(await closing, false);
  assert.equal(doc.model.isDisposed(), false);
  assert.equal(f.drafts.get(doc.path).content, 'new = 5;');
});

test('close failure never disposes the only in-memory copy', async t => {
  const f = fixture(t, { clearDraft: async () => { throw new Error('disk unavailable'); } }, async () => 'Discard');
  const doc = await dirtyFile(f);
  assert.equal(await f.editors.close(doc.path), false);
  assert.equal(doc.model.isDisposed(), false);
  assert.ok(f.logs.some(line => line.includes('Close canceled')));
});

test('close Save does not discard edits made during its write', async t => {
  const io = deferred();
  const f = fixture(t, { save: () => io.promise }, async () => 'Save');
  const doc = await dirtyFile(f);
  const closing = f.editors.close(doc.path);
  await nextTurn();
  doc.model.setValue('late = 8;');
  io.resolve(snapshot(doc.path, 'gain = 2;\n'));
  assert.equal(await closing, false);
  assert.equal(doc.model.isDisposed(), false);
  assert.equal(f.drafts.get(doc.path).content, 'late = 8;');
});

test('closeAll invalidates slow opens before a workspace can change', async t => {
  const io = deferred();
  const f = fixture(t, { read: () => io.promise });
  const opening = f.editors.open('control.m');
  const closing = f.editors.closeAll();
  await assert.rejects(f.editors.open('other.m'), /Editors are closing/);
  io.resolve(snapshot());
  await opening;
  assert.equal(await closing, true);
  assert.equal(f.models.length, 0, 'late read never allocates a model');
  f.files.read = async file => snapshot(file);
  await f.editors.open('control.m');
  assert.equal(f.editors.documents.size, 1, 'the next workspace may open normally');
});

test('closeAll also invalidates opens suspended in lazy editor loading', async t => {
  const io = deferred();
  const f = fixture(t);
  f.editors.ensureEditor = () => io.promise;
  const opening = f.editors.open('control.m');
  await nextTurn();
  const closing = f.editors.closeAll();
  io.resolve();
  await opening;
  assert.equal(await closing, true);
  assert.equal(f.models.length, 0);
});

test('late recovery reads cannot resurrect a closed model', async t => {
  const io = deferred();
  let prompts = 0;
  const f = fixture(t, { draft: () => io.promise }, async () => { prompts += 1; return 'Restore draft'; });
  const opening = f.editors.open('control.m');
  await nextTurn();
  const doc = f.editors.active;
  assert.equal(await f.editors.close(doc.path), true);
  io.resolve({ path: doc.path, content: 'recovered = 2;', base: snapshot() });
  await opening;
  assert.equal(prompts, 0);
  assert.equal(doc.model.isDisposed(), true);
  assert.equal(f.editors.documents.size, 0);
});

test('recovery does not overwrite typing made before the draft read completed', async t => {
  const io = deferred();
  let prompts = 0;
  const f = fixture(t, { draft: () => io.promise }, async () => { prompts += 1; return 'Restore draft'; });
  const opening = f.editors.open('control.m');
  await nextTurn();
  const doc = f.editors.active;
  doc.model.setValue('newer = 6;');
  io.resolve({ path: doc.path, content: 'older = 2;', base: snapshot() });
  await opening;
  assert.equal(doc.model.getValue(), 'newer = 6;');
  assert.equal(prompts, 0);
});

test('recovery choice cannot overwrite edits made after its prompt', async t => {
  const answer = deferred();
  const f = fixture(t, { draft: async () => ({ path: 'control.m', content: 'old = 2;', base: snapshot() }) }, () => answer.promise);
  const opening = f.editors.open('control.m');
  await nextTurn();
  const doc = f.editors.active;
  doc.model.setValue('newer = 9;');
  answer.resolve('Restore draft');
  await opening;
  assert.equal(doc.model.getValue(), 'newer = 9;');
});

test('ordinary recovery remains dirty against the original conflict-checking base', async t => {
  const base = snapshot('control.m', 'old disk = 1;');
  const f = fixture(t, { draft: async () => ({ path: 'control.m', content: 'draft = 2;', base }) }, async () => 'Restore draft');
  await f.editors.open('control.m');
  assert.equal(f.editors.active.base, base);
  assert.equal(f.editors.active.model.getValue(), 'draft = 2;');
  assert.equal(f.editors.dirty(f.editors.active), true);
});

test('draft failures after successful writes are reported without claiming disk save failed', async t => {
  const f = fixture(t, { clearDraft: async () => { throw new Error('draft unavailable'); } });
  const doc = await dirtyFile(f);
  await assert.rejects(f.editors.save(), /draft unavailable/);
  assert.equal(f.writes.length, 1);
  assert.equal(f.editors.dirty(doc), false);
  assert.ok(f.logs.some(line => line.includes('File saved, but recovery draft update failed')));
  assert.equal(f.logs.some(line => line.startsWith('Save failed:')), false);
});


test('closing during pending recovery preserves the unseen persisted draft', async t => {
  const io = deferred();
  const f = fixture(t, { draft: () => io.promise });
  const draft = { path: 'control.m', content: 'precious = 1;', base: snapshot() };
  f.drafts.set(draft.path, draft);
  const opening = f.editors.open(draft.path);
  await nextTurn();
  assert.equal(await f.editors.close(draft.path), true);
  io.resolve(draft);
  await opening;
  assert.equal(f.drafts.get(draft.path), draft);
});

test('canceling a recovery prompt preserves its draft when the clean tab closes', async t => {
  const f = fixture(t);
  const draft = { path: 'control.m', content: 'precious = 2;', base: snapshot() };
  f.drafts.set(draft.path, draft);
  await f.editors.open(draft.path);
  assert.equal(await f.editors.close(draft.path), true);
  assert.equal(f.drafts.get(draft.path), draft);
});

test('choosing Keep disk explicitly clears a recovery draft', async t => {
  const f = fixture(t, {}, async () => 'Keep disk');
  const draft = { path: 'control.m', content: 'old = 2;', base: snapshot() };
  f.drafts.set(draft.path, draft);
  await f.editors.open(draft.path);
  assert.equal(f.drafts.has(draft.path), false);
  assert.equal(f.editors.active.recoveryPending, false);
});

test('copy snapshot preserves unsaved source, BOM, base, undo and draft state', async t => {
  const f = fixture(t, { read: async file => snapshot(file, 'gain=1;\r\n', { bom: true, eol: 'CRLF' }) });
  const doc = await dirtyFile(f, 'control.m', 'gain=2;\r\n');
  const base = doc.base, clean = doc.cleanAlternativeVersionId, version = doc.model.getVersionId();
  f.drafts.set('control.m', { content: 'existing recovery' });
  const copy = f.editors.copySnapshot();
  doc.model.setValue('later=3;\r\n');
  assert.deepEqual(copy, { path: 'control.m', content: 'gain=2;\r\n', bom: true });
  assert.equal(doc.base, base); assert.equal(doc.cleanAlternativeVersionId, clean);
  assert.equal(f.editors.dirty(doc), true); assert.ok(doc.model.getVersionId() > version);
  assert.equal(doc.model.stops, 0); assert.deepEqual(f.writes, []);
  assert.equal(f.drafts.get('control.m').content, 'existing recovery');
});

test('copy snapshot works without re-reading a deleted source', async t => {
  const f = fixture(t); await dirtyFile(f);
  f.files.read = async () => { throw new Error('source deleted'); };
  assert.equal(f.editors.copySnapshot().content, 'gain = 2;\n');
});

test('copy snapshot rejects unavailable, closing or mixed-newline models', async t => {
  const f = fixture(t);
  assert.throws(() => f.editors.copySnapshot(), /Open a MATLAB/);
  const doc = await dirtyFile(f); doc.base.mixed_eol = true;
  assert.throws(() => f.editors.copySnapshot(), /Mixed line endings/);
  doc.base.mixed_eol = false; doc.closing = Promise.resolve(false);
  assert.throws(() => f.editors.copySnapshot(), /Open a MATLAB/);
});

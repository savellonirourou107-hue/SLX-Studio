// Actual Electron + Monaco + private Python backend. Fixtures never run MATLAB.
import assert from 'node:assert/strict';
import * as fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { _electron as electron } from 'playwright';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(import.meta.url);
const artifacts = path.join(root, 'output/playwright');
await fs.mkdir(artifacts, { recursive: true });
const testRoot = await fs.mkdtemp(path.join(os.tmpdir(), 'slx-create-e2e-'));
const workspace = path.join(testRoot, '工程');
await fs.mkdir(path.join(workspace, '实验'), { recursive: true });
const original = '\ufeff%% 控制\r\nKp = 2;';
await fs.writeFile(path.join(workspace, '控制.m'), original);
await fs.writeFile(path.join(workspace, 'mixed.m'), 'a=1;\r\nb=2;\n');
const monacoAsset = (await fs.readdir(path.join(root, 'dist/desktop/renderer'))).find(name => /^monaco-.*\.js$/.test(name));
assert.ok(monacoAsset);
const env = { ...process.env, SLX_DESKTOP_TEST_HIDE: '1', SLX_DESKTOP_STATE_DIR: path.join(testRoot, 'state'), SLX_DESKTOP_WORKSPACE: workspace };
delete env.ELECTRON_RUN_AS_NODE;
let app, page;
const errors = [];
async function waitFor(check, label) {
  const end = Date.now() + 10_000;
  do { if (await check()) return; await new Promise(resolve => setTimeout(resolve, 50)); } while (Date.now() < end);
  throw new Error(`Timed out: ${label}`);
}
async function exists(file) { try { await fs.lstat(file); return true; } catch (error) { if (error.code === 'ENOENT') return false; throw error; } }
async function command(title) {
  await page.getByRole('button', { name: 'Commands', exact: true }).click();
  await page.getByRole('textbox', { name: 'Search commands', exact: true }).fill(title);
  await page.getByRole('button', { name: title, exact: true }).click();
}
async function menu(label) {
  await app.evaluate(({ Menu, BrowserWindow }, label) => {
    const item = Menu.getApplicationMenu()?.items.find(item => item.label === 'File')?.submenu?.items.find(item => item.label === label);
    if (!item) throw new Error(`Missing File menu item: ${label}`);
    item.click?.(item, BrowserWindow.getFocusedWindow(), {});
  }, label);
}
async function replaceText(content) {
  await page.getByRole('tab', { selected: true }).click();
  await page.keyboard.press('Control+Home'); await page.keyboard.press('Control+A'); await page.keyboard.insertText(content);
}
async function editorText(file) {
  return page.evaluate(async ({ file, asset }) => {
    const { monaco } = await import(new URL(`./${asset}`, location.href));
    const model = monaco.editor.getModels().find(model => model.uri.path === `/${file}`);
    if (!model) throw new Error(`Missing model: ${file}`);
    return model.getValue();
  }, { file, asset: monacoAsset });
}
try {
  app = await electron.launch({ executablePath: require('electron'), args: [path.join(root, 'dist/desktop/electron/main.cjs')], cwd: root, env, chromiumSandbox: true, timeout: 30_000 });
  page = await app.firstWindow(); page.setDefaultTimeout(10_000);
  page.on('pageerror', error => errors.push(error.message));
  await page.locator('body[data-ready="true"]').waitFor();
  await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].showInactive());
  assert.equal(await page.evaluate(() => typeof window.require), 'undefined');
  const dialog = page.locator('#file-creation');
  const input = page.getByRole('textbox', { name: 'Workspace-relative .m path', exact: true });

  await command('File: New MATLAB File…'); await input.fill('cancelled.m'); await page.keyboard.press('Escape');
  await waitFor(async () => !await dialog.isVisible(), 'cancel closes the dialog');
  assert.equal(await exists(path.join(workspace, 'cancelled.m')), false);
  await menu('New MATLAB File…'); await input.fill('created.m');
  await dialog.getByRole('button', { name: 'Create file', exact: true }).click();
  await page.getByRole('tab', { name: 'created.m', selected: true }).waitFor();
  assert.equal(await fs.readFile(path.join(workspace, 'created.m'), 'utf8'), '');
  assert.equal(await editorText('created.m'), '');
  await page.getByRole('treeitem', { name: 'created.m', exact: true }).waitFor();
  await replaceText('fresh = 7;\n'); await page.keyboard.press('Control+s');
  await waitFor(async () => await fs.readFile(path.join(workspace, 'created.m'), 'utf8') === 'fresh = 7;\n', 'new file uses the normal versioned save flow');
  await page.getByRole('button', { name: 'Close created.m', exact: true }).click();

  await command('File: New MATLAB File…'); await input.fill('created.m');
  await dialog.getByRole('button', { name: 'Create file', exact: true }).click();
  await waitFor(async () => (await page.locator('#file-creation-status').textContent()).includes('already exists'), 'existing target reports a visible conflict');
  assert.equal(await fs.readFile(path.join(workspace, 'created.m'), 'utf8'), 'fresh = 7;\n');
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
  console.log('PASS: native-menu new file, real edit/save, cancel and no overwrite.');

  await page.getByRole('treeitem', { name: '控制.m', exact: true }).click();
  await replaceText('%% 控制\nKp = 19;');
  const copiedText = await editorText('控制.m');
  await command('File: Save Copy As…'); await input.fill('实验/副本.m');
  await dialog.getByRole('button', { name: 'Create copy', exact: true }).click();
  await page.getByRole('tab', { name: '实验/副本.m', selected: true }).waitFor();
  assert.equal(await fs.readFile(path.join(workspace, '实验/副本.m'), 'utf8'), '\ufeff' + copiedText);
  assert.equal(await editorText('实验/副本.m'), copiedText);
  assert.ok(copiedText.includes('\r\n')); assert.ok(!copiedText.endsWith('\n'));
  assert.equal(await fs.readFile(path.join(workspace, '控制.m'), 'utf8'), original);
  assert.equal(await editorText('控制.m'), copiedText);
  assert.match(await page.getByRole('tab', { name: '控制.m', exact: true }).textContent(), /●/);
  assert.doesNotMatch(await page.getByRole('tab', { name: '实验/副本.m', exact: true }).textContent(), /●/);
  await page.screenshot({ path: path.join(artifacts, 'desktop-save-copy.png') });
  await page.getByRole('button', { name: 'Close 实验/副本.m', exact: true }).click();
  await page.getByRole('button', { name: 'Close 控制.m', exact: true }).click();
  await page.getByRole('button', { name: 'Discard', exact: true }).click();
  console.log('PASS: copy preserves the unsaved source, Unicode/BOM/CRLF and no final newline.');

  await page.getByRole('treeitem', { name: 'created.m', exact: true }).click();
  await replaceText('rescued = 9;\n');
  await fs.rm(path.join(workspace, 'created.m'));
  await menu('Save Copy As…'); await input.fill('created.m');
  await dialog.getByRole('button', { name: 'Create copy', exact: true }).click();
  await waitFor(async () => (await page.locator('#file-creation-status').textContent()).includes('open editor'), 'deleted source path still protects its open buffer');
  assert.equal(await exists(path.join(workspace, 'created.m')), false);
  await input.fill('rescued.m');
  await dialog.getByRole('button', { name: 'Create copy', exact: true }).click();
  await page.getByRole('tab', { name: 'rescued.m', selected: true }).waitFor();
  assert.equal(await fs.readFile(path.join(workspace, 'rescued.m'), 'utf8'), 'rescued = 9;\n');
  assert.equal(await exists(path.join(workspace, 'created.m')), false);
  assert.match(await page.getByRole('tab', { name: 'created.m', exact: true }).textContent(), /●/);
  await page.getByRole('button', { name: 'Close rescued.m', exact: true }).click();
  await page.getByRole('button', { name: 'Close created.m', exact: true }).click();
  await page.getByRole('button', { name: 'Discard', exact: true }).click();
  console.log('PASS: a deleted source can be rescued as a copy without replacing its dirty buffer.');

  await page.getByRole('treeitem', { name: 'mixed.m', exact: true }).click();
  await command('File: Save Copy As…');
  await waitFor(async () => (await page.locator('#output').textContent()).includes('copying the normalized editor buffer is disabled'), 'mixed-newline buffer is not silently converted by copy');
  assert.equal(await dialog.isVisible(), false);
  assert.equal(await fs.readFile(path.join(workspace, 'mixed.m'), 'utf8'), 'a=1;\r\nb=2;\n');

  const guards = await page.evaluate(async () => {
    const info = await window.slx.workspace(); if (!info.ok || !info.value) throw new Error('Missing workspace');
    return Promise.all([
      window.slx.createDocument(info.value.root, '../outside.m', 'x', false),
      window.slx.createDocument(info.value.root, '.git/hook.m', 'x', false),
      window.slx.createDocument(info.value.root + '-stale', 'stale.m', 'x', false),
      window.slx.createDocument(info.value.root, 'bad-bom.m', 'x', 'false'),
    ]);
  });
  assert.ok(guards.every(result => result.ok === false));
  assert.equal(await exists(path.join(testRoot, 'outside.m')), false);
  assert.equal(await exists(path.join(workspace, 'stale.m')), false);
  assert.equal(await exists(path.join(workspace, 'bad-bom.m')), false);
  const foreign = await app.evaluate(async ({ BrowserWindow }, { preload, workspace }) => {
    const window = new BrowserWindow({ show: false, webPreferences: { preload, contextIsolation: true, sandbox: true, nodeIntegration: false } });
    try {
      await window.loadURL('slx-app://workbench/index.html');
      return await window.webContents.executeJavaScript(`window.slx.createDocument(${JSON.stringify(workspace)}, "foreign.m", "x", false)`);
    } finally { window.destroy(); }
  }, { preload: path.join(root, 'dist/desktop/electron/preload.cjs'), workspace });
  assert.equal(foreign.ok, false); assert.equal(await exists(path.join(workspace, 'foreign.m')), false);
  const runtime = await page.evaluate(() => window.slx.matlabStatus());
  assert.equal(runtime.ok, true); assert.equal(runtime.value.state, 'stopped');
  assert.deepEqual(errors, []);
  console.log('PASS: create IPC rejects foreign frames, stale workspace, traversal and malformed payloads; MATLAB stays stopped.');
} catch (error) {
  if (page && !page.isClosed()) {
    console.error(await page.locator('body').ariaSnapshot().catch(() => 'No snapshot'));
    await page.screenshot({ path: path.join(artifacts, 'file-creation-failure.png') }).catch(() => {});
  }
  throw error;
} finally {
  await app?.close().catch(() => {});
  console.log(`File creation fixtures: ${testRoot}`);
}

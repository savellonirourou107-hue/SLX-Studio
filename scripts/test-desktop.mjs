// Real Electron smoke/interaction coverage. No browser mock or MATLAB process.
import assert from 'node:assert/strict';
import * as fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { _electron as electron } from 'playwright';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(import.meta.url);
const artifactRoot = path.join(root, 'output/playwright');
await fs.mkdir(artifactRoot, { recursive: true });
const testRoot = await fs.mkdtemp(path.join(os.tmpdir(), 'slx-desktop-e2e-'));
const workspace = path.join(testRoot, '工程');
await fs.mkdir(workspace);
await fs.writeFile(path.join(workspace, 'control.m'), 'gain = 1;\n');
await fs.writeFile(path.join(workspace, '控制.m'), '\ufeff%% 控制\r\nKp = 2;');
await fs.writeFile(path.join(workspace, 'model.slx'), 'static fixture');
await fs.writeFile(path.join(workspace, 'mixed.m'), 'a = 1;\r\nb = 2;\n');
const env = { ...process.env, SLX_DESKTOP_TEST_HIDE: '1', SLX_DESKTOP_STATE_DIR: path.join(testRoot, 'state'), SLX_DESKTOP_WORKSPACE: workspace };
delete env.ELECTRON_RUN_AS_NODE;
let application;
let page;
const errors = [];
async function waitFor(check, label) {
  const end = Date.now() + 10_000;
  do {
    if (await check()) return;
    await new Promise(resolve => setTimeout(resolve, 50));
  } while (Date.now() < end);
  throw new Error(`Timed out: ${label}`);
}
async function replaceText(content) {
  await page.getByRole('tab', { selected: true }).click();
  await page.keyboard.press('Control+Home');
  await page.keyboard.press('Control+A');
  await page.keyboard.insertText(content);
}
async function command(title) {
  await page.getByRole('button', { name: 'Commands', exact: true }).click();
  await page.getByRole('textbox', { name: 'Search commands', exact: true }).fill(title);
  await page.getByRole('button', { name: title, exact: true }).click();
}
async function launch() {
  application = await electron.launch({ executablePath: require('electron'), args: [path.join(root, 'dist/desktop/electron/main.cjs')], cwd: root, env, chromiumSandbox: true, timeout: 30_000 });
  page = await application.firstWindow();
  page.setDefaultTimeout(10_000);
  page.on('pageerror', error => errors.push(error.message));
  await page.locator('body[data-ready="true"]').waitFor();
  await application.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].showInactive());
  console.log(await page.locator('body').ariaSnapshot());
}
async function closeForTest() {
  if (!application) return;
  await application.evaluate(({ BrowserWindow }) => { for (const window of BrowserWindow.getAllWindows()) window.destroy(); }).catch(() => {});
  await application.close().catch(() => {});
  application = undefined;
  page = undefined;
}
try {
  console.log('STEP launch');
  await launch();
  console.log('STEP isolation');
  assert.equal(await page.evaluate(() => typeof window.process), 'undefined');
  assert.equal(await page.evaluate(() => typeof window.require), 'undefined');
  assert.equal(await page.evaluate(() => typeof window.slx.invoke), 'undefined');
  await page.getByRole('treeitem', { name: 'control.m', exact: true }).click();
  await page.getByRole('treeitem', { name: 'model.slx', exact: true }).click();
  await waitFor(async () => (await page.getByRole('log').textContent()).includes('no registered editor in this desktop'), 'unimplemented SLX viewport is explicit');
  await command('Settings: Show Effective Configuration');
  await waitFor(async () => (await page.getByRole('log').textContent()).includes('"editor.fontSize": 14'), 'effective settings are exposed through a command');
  await page.getByRole('button', { name: 'Clear', exact: true }).click();
  await page.getByRole('treeitem', { name: 'model.slx', exact: true }).click();
  await waitFor(async () => (await page.getByRole('log').textContent()).includes('no registered editor in this desktop'), 'output can be cleared and reused');
  assert.ok(!(await page.getByRole('log').textContent()).includes('editor.fontSize'), 'cleared output does not reappear');
  await page.getByRole('treeitem', { name: 'mixed.m', exact: true }).click();
  await page.getByRole('tab', { name: 'mixed.m', exact: true }).waitFor();
  assert.equal(await page.getByRole('tab', { name: 'mixed.m', exact: true }).textContent(), 'mixed.m', 'mixed EOL file does not become falsely dirty');
  await page.getByRole('button', { name: 'Close mixed.m', exact: true }).click();
  await page.getByRole('treeitem', { name: 'control.m', exact: true }).click();
  console.log('STEP first edit');
  await page.getByRole('tab', { name: 'control.m', exact: true }).waitFor();
  await replaceText('gain = 3;\n');
  await page.keyboard.press('Control+z');
  await page.keyboard.press('Control+s');
  assert.equal(await fs.readFile(path.join(workspace, 'control.m'), 'utf8'), 'gain = 1;\n', 'undo restores the original model');
  await page.keyboard.press('Control+y');
  await page.keyboard.press('Control+s');
  await waitFor(async () => await fs.readFile(path.join(workspace, 'control.m'), 'utf8') === 'gain = 3;\n', 'shortcut saves real file after undo/redo');
  await page.keyboard.press('Control+f');
  await page.keyboard.insertText('gain');
  await waitFor(async () => await page.locator('.find-widget').isVisible(), 'Monaco find widget opens');
  await page.keyboard.press('Escape');
  await page.keyboard.press('Control+h');
  await waitFor(async () => await page.locator('.find-widget').isVisible(), 'Monaco replace widget opens');
  await page.locator('.find-widget textarea[aria-label="Find"]').fill('gain');
  await page.locator('.find-widget textarea[aria-label="Replace"]').fill('value');
  await page.getByRole('button', { name: /Replace All/ }).click();
  await page.keyboard.press('Escape');
  await page.keyboard.press('Control+s');
  await waitFor(async () => await fs.readFile(path.join(workspace, 'control.m'), 'utf8') === 'value = 3;\n', 'replace-all changes only the active model');
  console.log('STEP second file');
  await page.getByRole('treeitem', { name: '控制.m', exact: true }).click();
  await page.getByRole('tab', { name: '控制.m', exact: true }).waitFor();
  await replaceText('%% 控制\nKp = 5;');
  await command('File: Save');
  await waitFor(async () => await fs.readFile(path.join(workspace, '控制.m'), 'utf8') === '\ufeff%% 控制\r\nKp = 5;', 'Unicode/BOM/CRLF/no-final-newline preserved');
  await page.getByRole('tab', { name: 'control.m', exact: true }).click();
  await replaceText('menu = 3;\n');
  await application.evaluate(({ Menu, BrowserWindow }) => {
    const file = Menu.getApplicationMenu()?.items.find(item => item.label === 'File');
    const save = file?.submenu?.items.find(item => item.label === 'Save');
    save?.click?.(save, BrowserWindow.getFocusedWindow(), {});
  });
  await waitFor(async () => await fs.readFile(path.join(workspace, 'control.m'), 'utf8') === 'menu = 3;\n', 'application menu invokes the shared save command');
  assert.equal(await page.getByRole('tab').count(), 2);
  const escape = await page.evaluate(() => window.slx.readDocument('../escape.m'));
  console.log('STEP conflict');
  assert.equal(escape.ok, false, 'workspace escape is rejected by the typed API');
  await page.getByRole('tab', { name: 'control.m', exact: true }).click();
  await replaceText('gain = 4;\n');
  await page.keyboard.press('Control+s');
  await waitFor(async () => await fs.readFile(path.join(workspace, 'control.m'), 'utf8') === 'gain = 4;\n', 'second file edit uses its own Monaco model');
  await fs.writeFile(path.join(workspace, 'control.m'), 'external = 1;\n');
  await replaceText('gain = 5;\n');
  await page.keyboard.press('Control+s');
  await waitFor(async () => (await page.getByRole('log').textContent()).includes('Save failed'), 'external modification reports conflict');
  assert.equal(await fs.readFile(path.join(workspace, 'control.m'), 'utf8'), 'external = 1;\n');
  const foreignPreload = path.join(root, 'dist/desktop/electron/preload.cjs');
  const foreignResult = await application.evaluate(async ({ BrowserWindow }, preload) => {
    const foreign = new BrowserWindow({ show: false, webPreferences: { preload, contextIsolation: true, sandbox: true, nodeIntegration: false } });
    await foreign.loadURL('slx-app://workbench/index.html');
    const result = await foreign.webContents.executeJavaScript('window.slx.readDocument("control.m")');
    foreign.destroy();
    return result;
  }, foreignPreload);
  assert.equal(foreignResult.ok, false, 'IPC rejects a foreign renderer frame');
  await command('File: Reload from Disk');
  await page.getByRole('button', { name: 'Reload', exact: true }).click();
  await page.getByRole('tab', { name: 'control.m', exact: true }).click();
  await replaceText('unsaved = 6;\n');
  await page.getByRole('button', { name: 'Close control.m', exact: true }).click();
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  assert.equal(await page.getByRole('tab', { name: 'control.m', exact: true }).count(), 1, 'cancel keeps dirty tab');
  await page.getByRole('button', { name: 'Close control.m', exact: true }).click();
  await page.getByRole('button', { name: 'Discard', exact: true }).click();
  console.log('STEP draft');
  assert.equal(await page.getByRole('tab', { name: 'control.m', exact: true }).count(), 0, 'discard disposes tab');
  await page.getByRole('treeitem', { name: 'control.m', exact: true }).click();
  await replaceText('draft = 8;\n');
  await new Promise(resolve => setTimeout(resolve, 700));
  await application.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].showInactive());
  await page.screenshot({ path: path.join(artifactRoot, 'desktop-editing.png') });
  assert.deepEqual(errors, []);
  console.log('PASS: real Electron startup, isolated renderer, multi-model undo/find/save/conflict/dirty-close workflows.');
  console.log('STEP restart');
  await closeForTest();
  await launch();
  await page.getByRole('treeitem', { name: 'control.m', exact: true }).click();
  await page.getByRole('button', { name: 'Restore draft', exact: true }).click();
  await command('File: Save');
  await waitFor(async () => await fs.readFile(path.join(workspace, 'control.m'), 'utf8') === 'draft = 8;\n', 'draft recovery saves through the normal service');
  console.log('PASS: persistent draft recovery after an application restart.');
  await page.getByRole('treeitem', { name: 'control.m', exact: true }).click();
  await replaceText('window = 9;\n');
  await application.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].close());
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  assert.equal(page.isClosed(), false, 'window close cancellation keeps the dirty workbench');
  await page.getByRole('button', { name: 'Close control.m', exact: true }).click();
  await page.getByRole('button', { name: 'Discard', exact: true }).click();
  for (let cycle = 0; cycle < 100; cycle += 1) {
    await page.getByRole('treeitem', { name: 'control.m', exact: true }).click();
    await page.getByRole('tab', { name: 'control.m', exact: true }).waitFor();
    await page.getByRole('button', { name: 'Close control.m', exact: true }).click();
  }
  const monacoAsset = (await fs.readdir(path.join(root, 'dist/desktop/renderer'))).find(name => /^monaco-.*\.js$/.test(name));
  assert.ok(monacoAsset);
  const remainingModels = await page.evaluate(async asset => (await import(new URL(`./${asset}`, location.href))).monaco.editor.getModels().length, monacoAsset);
  assert.equal(remainingModels, 0, '100 open/close cycles dispose Monaco models');
  console.log('PASS: 100 editor open/close cycles leave no retained Monaco models.');
} catch (error) {
  if (page && !page.isClosed()) {
    console.error(await page.locator('body').ariaSnapshot());
    await application.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].showInactive()).catch(() => {});
    await page.screenshot({ path: path.join(artifactRoot, 'desktop-failure.png') }).catch(() => {});
  }
  console.error('Renderer errors:', errors);
  throw error;
} finally {
  // This deliberately bypasses the user-close prompt only for fixture cleanup.
  await closeForTest();
  // Keep failure fixtures for diagnosis; this is a bounded generated directory.
  console.log(`Electron fixtures: ${testRoot}`);
}

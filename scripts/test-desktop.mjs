// Real Electron smoke/interaction coverage. No browser mock or MATLAB process.
import assert from 'node:assert/strict';
import * as fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
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
const modelXml = '<System><Block BlockType="Inport" Name="Input" SID="1"/><Block BlockType="Gain" Name="Gain" SID="2"><P Name="VariantControl">A</P></Block><Line><P Name="Src">1#out:1</P><P Name="Dst">2#in:1</P></Line></System>';
execFileSync(process.env.SLX_STUDIO_PYTHON || 'python', [
  '-c',
  'import zipfile,sys; z=zipfile.ZipFile(sys.argv[1], "w"); z.writestr("simulink/systems/system_root.xml", sys.argv[2]); z.close()',
  path.join(workspace, 'model.slx'),
  modelXml,
], { windowsHide: true });
const largeXmlPath = path.join(testRoot, 'large-system.xml');
const largeBlocks = Array.from({ length: 1000 }, (_, index) => `<Block BlockType="Gain" Name="Block${String(index).padStart(4, '0')}" SID="${index + 1}"><P Name="Position">[${20 + (index % 10) * 130} ${40 + Math.floor(index / 10) * 70} ${80 + (index % 10) * 130} ${70 + Math.floor(index / 10) * 70}]</P></Block>`).join('');
const largeLines = Array.from({ length: 999 }, (_, index) => `<Line><P Name="Src">${index + 1}#out:1</P><P Name="Dst">${index + 2}#in:1</P></Line>`).join('');
await fs.writeFile(largeXmlPath, `<System>${largeBlocks}${largeLines}</System>`);
execFileSync(process.env.SLX_STUDIO_PYTHON || 'python', [
  '-c', 'import zipfile,sys; z=zipfile.ZipFile(sys.argv[1], "w"); z.writestr("simulink/systems/system_root.xml", open(sys.argv[2], encoding="utf-8").read()); z.close()',
  path.join(workspace, 'large.slx'), largeXmlPath,
], { windowsHide: true });
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
  await waitFor(async () => (await page.getByRole('log').textContent()).includes('static model view'), 'SLX static model view is exposed through the custom editor contribution');
  assert.match(await page.getByRole('log').textContent(), /2 blocks, 1 connections/);
  await command('Extensions: Activate Trusted Extension…');
  await waitFor(async () => (await page.getByRole('log').textContent()).includes('Extension activated: sample.hello'), 'trusted extension activation is explicit and contributes a view');
  assert.match(await page.locator('#extension-views').textContent(), /Sample Inspector/);
  await command('Sample: Hello SLX Studio');
  await waitFor(async () => (await page.getByRole('log').textContent()).includes('Hello from the trusted SLX Studio extension host.'), 'extension command executes in the private host');
  await command('Extensions: Deactivate Active Extension');
  await waitFor(async () => !(await page.locator('#extension-views').textContent()).includes('Sample Inspector'), 'extension deactivation releases contributed views');
  await page.getByRole('group', { name: 'Static model canvas' }).waitFor();
  await page.getByRole('group', { name: 'Static model canvas' }).getByRole('button', { name: 'Block Gain (Gain)' }).click();
  assert.match(await page.getByRole('complementary').last().textContent(), /Gain/);
  await page.getByRole('textbox', { name: 'Find model blocks' }).fill('Input');
  await waitFor(async () => await page.getByRole('button', { name: 'Inspect Gain', exact: true }).count() === 0, 'model search filters the bounded outline');
  assert.equal(await page.getByRole('button', { name: 'Inspect Gain', exact: true }).count(), 0, 'model search filters the bounded outline');
  await page.getByRole('textbox', { name: 'Find model blocks' }).fill('');
  await page.getByRole('treeitem', { name: 'large.slx', exact: true }).click();
  await waitFor(async () => await page.getByRole('button', { name: 'Next blocks', exact: true }).isEnabled(), 'large model viewport exposes a bounded next page');
  assert.equal(await page.getByRole('group', { name: 'Static model canvas' }).getByRole('button').count(), 160, 'large model rendering is bounded to one page');
  await page.getByRole('button', { name: 'Next blocks', exact: true }).click();
  await waitFor(async () => (await page.getByText(/161–320 \/ 1000 matching blocks/).count()) === 1, 'large model viewport advances by bounded pages');
  await page.getByRole('textbox', { name: 'Find model blocks' }).fill('Block0999');
  await waitFor(async () => await page.getByRole('button', { name: 'Inspect Block0999', exact: true }).count() === 1, 'large model viewport filters without expanding the DOM');
  await page.getByRole('treeitem', { name: 'model.slx', exact: true }).click();
  await page.getByRole('button', { name: /PROBLEMS/ }).click();
  await page.locator('#problems .problem-row').waitFor();
  assert.match(await page.locator('#problems').textContent(), /variant/);
  await page.locator('#problems .problem-row').click();
  await waitFor(async () => (await page.getByRole('log').textContent()).includes('static model view'), 'clicking a problem navigates to its registered model contribution');
  const sameModelDiff = await page.evaluate(() => window.slx.diffModels('model.slx', 'model.slx', false));
  assert.equal(sameModelDiff.ok, true);
  assert.equal(sameModelDiff.value.changed, false, 'typed model diff reports identical files');
  const modelPage = await page.evaluate(() => window.slx.inspectModel('model.slx', { blockCursor: 1, pageSize: 1 }));
  assert.equal(modelPage.ok, true);
  assert.equal(modelPage.value.blocks.length, 1);
  assert.equal(modelPage.value.total_blocks, 2);
  assert.equal(modelPage.value.next_block_cursor, null);
  const invalidModelPage = await page.evaluate(() => window.slx.inspectModel('model.slx', { pageSize: 0 }));
  assert.equal(invalidModelPage.ok, false, 'desktop IPC rejects an empty model page');
  await command('Workbench: Reload Built-in Contributions');
  await waitFor(async () => (await page.getByRole('log').textContent()).includes('Workbench contributions reloaded'), 'built-in contributions can be reloaded without leaking registrations');
  await page.getByRole('treeitem', { name: 'model.slx', exact: true }).click();
  await waitFor(async () => (await page.getByRole('log').textContent()).includes('static model view'), 'reloaded contributions restore the Simulink editor');
  await command('Settings: Edit Configuration');
  await page.locator('#settings-scope').selectOption('workspace');
  await page.locator('#settings-font-size').fill('16');
  await page.screenshot({ path: path.join(artifactRoot, 'desktop-settings.png') });
  await page.getByRole('button', { name: 'Apply settings', exact: true }).click();
  await waitFor(async () => (await page.getByRole('log').textContent()).includes('Settings saved (workspace)'), 'workspace settings are persisted through the typed service');
  assert.match(await fs.readFile(path.join(workspace, '.slx-studio', 'settings.json'), 'utf8'), /"editor\.fontSize": 16/);
  await command('Settings: Show Effective Configuration');
  await waitFor(async () => (await page.getByRole('log').textContent()).includes('"editor.fontSize": 16'), 'persisted settings affect the effective configuration');
  assert.equal(await page.locator('#monaco .view-lines').evaluate(node => getComputedStyle(node).fontSize), '16px', 'saved font size changes the actual Monaco editor');
  await command('Backend: Restart Python Service');
  await waitFor(async () => (await page.getByRole('log').textContent()).includes('Python backend restarted'), 'backend restart is explicit and does not replay requests');
  const restarts = await page.evaluate(() => Promise.all([window.slx.restartBackend(), window.slx.restartBackend()]));
  assert.equal(restarts.filter(result => result.ok).length, 1, 'concurrent backend transitions are rejected instead of leaking workers');
  await page.getByRole('button', { name: 'Clear', exact: true }).click();
  await page.getByRole('treeitem', { name: 'model.slx', exact: true }).click();
  await waitFor(async () => (await page.getByRole('log').textContent()).includes('static model view'), 'output can be cleared and reused');
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
  assert.equal(await page.getByRole('tab').count(), 4, 'text and multiple model tabs coexist in one workbench');
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
  await command('Settings: Show Effective Configuration');
  await waitFor(async () => (await page.getByRole('log').textContent()).includes('"editor.fontSize": 16'), 'workspace settings survive an application restart');
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

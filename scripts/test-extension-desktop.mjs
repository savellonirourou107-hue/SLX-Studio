// A real, isolated Electron renderer must stay editable while its trusted Node
// extension loops forever. No MATLAB process or private user workspace is used.
import assert from 'node:assert/strict';
import * as fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { _electron as electron } from 'playwright';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(import.meta.url);
const fixture = await fs.mkdtemp(path.join(os.tmpdir(), 'slx-extension-e2e-'));
const workspace = path.join(fixture, 'workspace');
const trusted = path.join(fixture, 'trusted');
const faulty = path.join(trusted, 'zzfault.ext');
await fs.mkdir(workspace);
await fs.mkdir(faulty, { recursive: true });
await fs.cp(path.join(root, 'extensions/sample.hello'), path.join(trusted, 'sample.hello'), { recursive: true });
await fs.writeFile(path.join(workspace, 'control.m'), 'gain = 1;\n');
await fs.writeFile(path.join(workspace, 'demo.slxpreview'), 'sample editor payload\n');
await fs.writeFile(path.join(faulty, 'slx-extension.json'), JSON.stringify({
  id: 'zzfault.ext', apiVersion: 1, version: '1.0.0', main: 'extension.mjs', activationEvents: ['onCommand:zzfault.run'],
  contributes: { commands: [{ command: 'zzfault.run', title: 'Fault: Run' }], views: [{ id: 'zzfault.view', title: 'Fault Inspector', location: 'sidebar' }] },
}));
await fs.writeFile(path.join(faulty, 'extension.mjs'), 'export function execute(){while(true){}}');
const env = { ...process.env, SLX_STUDIO_EXTENSION_ROOT: trusted, SLX_DESKTOP_TEST_HIDE: '1', SLX_DESKTOP_WORKSPACE: workspace, SLX_DESKTOP_STATE_DIR: path.join(fixture, 'state') };
delete env.ELECTRON_RUN_AS_NODE;
let application;
let page;
async function command(title) {
  await page.getByRole('button', { name: 'Commands', exact: true }).click();
  await page.getByRole('textbox', { name: 'Search commands', exact: true }).fill(title);
  await page.getByRole('button', { name: title, exact: true }).click();
}
async function waitFor(check, label, timeout = 10_000) {
  const deadline = Date.now() + timeout;
  do { if (await check()) return; await new Promise(resolve => setTimeout(resolve, 50)); } while (Date.now() < deadline);
  throw new Error(`Timed out: ${label}`);
}
try {
  application = await electron.launch({ executablePath: require('electron'), args: [path.join(root, 'dist/desktop/electron/main.cjs')], cwd: root, env, chromiumSandbox: true });
  page = await application.firstWindow(); page.setDefaultTimeout(10_000);
  await page.locator('body[data-ready="true"]').waitFor();
  const listed = await page.evaluate(() => window.slx.extensionsList());
  assert.equal(listed.ok, true);
  assert.ok(listed.value.every(item => item.state === 'inactive'));
  await command('Extensions: Activate Trusted Extension…');
  await page.getByText('Sample Inspector', { exact: false }).waitFor();
  await page.getByRole('treeitem', { name: 'demo.slxpreview', exact: true }).click();
  await page.getByRole('tab', { name: 'demo.slxpreview', exact: true }).waitFor();
  assert.match(await page.locator('.custom-editor').textContent(), /Sample Preview/);
  await command('Extensions: Activate Trusted Extension…');
  await page.getByText('Fault Inspector', { exact: false }).waitFor();
  await command('Fault: Run');
  const started = Date.now();
  await page.getByRole('treeitem', { name: 'control.m', exact: true }).click();
  await page.getByRole('tab', { name: 'control.m', exact: true }).click();
  await page.keyboard.press('Control+End');
  await page.keyboard.insertText('% saved while extension was hung\n');
  await page.keyboard.press('Control+s');
  await waitFor(async () => (await fs.readFile(path.join(workspace, 'control.m'), 'utf8')).includes('saved while extension was hung'), 'renderer can save with a busy host', 3000);
  assert.ok(Date.now() - started < 5000, 'saving completed before the extension timeout');
  await waitFor(async () => !(await page.locator('#extension-views').textContent()).includes('Fault Inspector'), 'timeout disposes failed contributions');
  assert.match(await page.getByRole('log').textContent(), /Extension failed: zzfault.ext/);
  assert.match(await page.locator('#extension-views').textContent(), /Sample Inspector/, 'another extension remains active');
  await fs.writeFile(path.join(faulty, 'extension.mjs'), 'export function execute(){return "recovered without replay"}');
  await command('Extensions: Restart Failed Extension…');
  await page.getByText('Fault Inspector', { exact: false }).waitFor();
  await command('Fault: Run');
  await waitFor(async () => (await page.getByRole('log').textContent()).includes('recovered without replay'), 'explicit restart restores only the failed extension');
  // Windows cannot remove the current working directory of a running child.
  // Removing its manifest marks uninstall intent; discovery must first stop
  // the host, after which the generated extension directory is removable.
  await fs.rm(path.join(faulty, 'slx-extension.json'));
  await command('Extensions: List Trusted Extensions');
  await page.evaluate(() => window.slx.extensionsList());
  await waitFor(async () => !(await page.locator('#extension-views').textContent()).includes('Fault Inspector'), 'removing a trusted extension releases its view and host');
  await command('Extensions: Deactivate Active Extension');
  await waitFor(async () => await page.locator('.custom-editor').count() === 0, 'deactivating sample releases its custom editor tab');
  await fs.rm(faulty, { recursive: true, force: true });
  console.log('PASS: extension hang leaves editing/saving responsive; failed-host cleanup, explicit restart and removal execute in real Electron.');
} catch (error) {
  if (page && !page.isClosed()) console.error(await page.locator('body').ariaSnapshot());
  throw error;
} finally {
  await application?.close().catch(() => {});
  await fs.rm(fixture, { recursive: true, force: true });
}

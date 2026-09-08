// Opt-in R2026a + actual Electron end-to-end acceptance. Not a fake worker test.
import assert from 'node:assert/strict';
import * as fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import { execFile } from 'node:child_process';
import { _electron as electron } from 'playwright';

if (!process.env.SLX_STUDIO_MATLAB) throw new Error('Set SLX_STUDIO_MATLAB to the real MATLAB executable before running this opt-in gate.');
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(import.meta.url);
const fixture = await fs.mkdtemp(path.join(os.tmpdir(), 'slx-matlab-e2e-'));
const workspace = path.join(fixture, 'workspace');
await fs.mkdir(workspace);
const { stdout: modelOutput } = await promisify(execFile)(process.env.PYTHON || 'D:\\python\\python.exe', ['-c',
  "import sys; sys.path.insert(0, 'tests'); from test_matlab_r2026a_integration import create_rpc_model; print(create_rpc_model(__import__('pathlib').Path(sys.argv[1]), sys.argv[2]))",
  fixture, process.env.SLX_STUDIO_MATLAB], { cwd: root, env: { ...process.env, PYTHONPATH: path.join(root, 'src') }, timeout: 180_000 });
await fs.copyFile(modelOutput.trim(), path.join(workspace, 'rpc_model.slx'));
await fs.writeFile(path.join(workspace, 'controller.m'), 'script_value = value + 1;\n%% Working section\nsection_value = value * 2;\n%% Not selected\nuntouched = 99;\n');
const env = { ...process.env, SLX_DESKTOP_TEST_HIDE: '1', SLX_DESKTOP_WORKSPACE: workspace, SLX_DESKTOP_STATE_DIR: path.join(fixture, 'state') };
delete env.ELECTRON_RUN_AS_NODE;
let application;
let page;
async function command(title) {
  await page.getByRole('button', { name: 'Commands', exact: true }).click();
  await page.getByRole('textbox', { name: 'Search commands', exact: true }).fill(title);
  await page.getByRole('button', { name: title, exact: true }).click();
}
async function waitFor(check, label, timeout = 90_000) {
  const deadline = Date.now() + timeout;
  do { if (await check()) return; await new Promise(resolve => setTimeout(resolve, 100)); } while (Date.now() < deadline);
  throw new Error(`Timed out: ${label}`);
}
async function input(text) {
  await page.getByRole('button', { name: 'OUTPUT', exact: true }).click();
  await command('MATLAB: Run Command Window Input…');
  await page.getByRole('textbox', { name: 'MATLAB command', exact: true }).fill(text);
  await page.getByRole('button', { name: 'Run command', exact: true }).click();
}
async function resultAfter(previous) {
  await waitFor(async () => {
    const id = await page.locator('#matlab-results').getAttribute('data-job-id');
    return !!id && id !== previous;
  }, 'new MATLAB job result');
  return page.locator('#matlab-results').getAttribute('data-job-id');
}
async function variable(name, expected) {
  await waitFor(async () => (await page.locator(`[data-variable-name="${name}"]`).textContent())?.includes(expected), `${name} = ${expected}`);
}
try {
  application = await electron.launch({ executablePath: require('electron'), args: [path.join(root, 'dist/desktop/electron/main.cjs')], cwd: root, env, chromiumSandbox: true });
  page = await application.firstWindow(); page.setDefaultTimeout(15_000);
  await page.locator('body[data-ready="true"]').waitFor();
  const idle = await page.evaluate(() => window.slx.matlabStatus());
  assert.equal(idle.ok, true); assert.equal(idle.value.state, 'stopped');
  await input("release_marker=version('-release'); value=5; fprintf(1,'stream-first'); pause(3); fprintf(1,'stream-last'); figure('Visible','off'); plot([0 1],[0 1]); title('Desktop acceptance');");
  await waitFor(async () => /(?:^|\n)stream-first/.test(await page.locator('#output').textContent()), 'non-newline output before completion');
  assert.match(await page.locator('.session-state').textContent(), /running/, 'console output is visible while the MATLAB job is still running');
  let job = await resultAfter(null);
  await page.getByRole('button', { name: 'MATLAB', exact: true }).click();
  await variable('value', '5'); await variable('release_marker', '2026a');
  const session = await page.locator('#matlab-results').getAttribute('data-session-id');
  assert.ok(session);
  await page.getByRole('img', { name: 'Figure 1', exact: true }).waitFor();
  assert.ok(await page.getByRole('img', { name: 'Figure 1', exact: true }).evaluate(image => image.complete && image.naturalWidth > 0));
  await page.getByRole('button', { name: 'Edit variable value', exact: true }).click();
  await page.getByRole('textbox', { name: 'Variable expression', exact: true }).fill('7');
  await page.getByRole('button', { name: 'Apply variable', exact: true }).click();
  job = await resultAfter(job); await variable('value', '7');
  assert.equal(await page.locator('#matlab-results').getAttribute('data-session-id'), session);
  await page.getByRole('treeitem', { name: 'controller.m', exact: true }).click();
  await command('MATLAB: Run Active Script');
  job = await resultAfter(job); await variable('script_value', '8');
  await page.getByRole('button', { name: 'Edit variable value', exact: true }).click();
  await page.getByRole('textbox', { name: 'Variable expression', exact: true }).fill('11');
  await page.getByRole('button', { name: 'Apply variable', exact: true }).click();
  job = await resultAfter(job);
  await page.getByRole('tab', { name: 'controller.m', exact: true }).click();
  await page.keyboard.press('Control+Home'); await page.keyboard.press('ArrowDown'); await page.keyboard.press('ArrowDown');
  await command('MATLAB: Run Current Section');
  job = await resultAfter(job); await variable('section_value', '22'); await variable('script_value', '8');
  assert.equal(await page.locator('#matlab-results').getAttribute('data-session-id'), session, 'command, variable, script and section share one owned session');
  await page.getByRole('tab', { name: 'controller.m', exact: true }).click();
  await page.keyboard.press('Control+a'); await page.keyboard.insertText("first=1;\nerror('slx:test','desktop diagnostic');\n");
  await command('MATLAB: Run Active Script');
  await page.getByRole('button', { name: 'Save and Run', exact: true }).click();
  job = await resultAfter(job);
  await page.getByRole('button', { name: /PROBLEMS/ }).click();
  await page.locator('.problem-row').filter({ hasText: 'desktop diagnostic' }).click();
  assert.match(await page.locator('#document-status').textContent(), /Ln 2, Col 1/, 'MATLAB diagnostics navigate to their actual source line');
  await input('pause(30);');
  await waitFor(async () => (await page.locator('.session-state').textContent()).includes('running'), 'long job starts');
  await command('MATLAB: Stop Active Job');
  job = await resultAfter(job);
  assert.match(await page.getByRole('log').textContent(), /state was lost\/reset/);
  await input("recovered=exist('value','var');");
  job = await resultAfter(job); await variable('recovered', '0');
  assert.notEqual(await page.locator('#matlab-results').getAttribute('data-session-id'), session, 'cancelled state is not silently replayed');
  // Kill only this app's Python supervisor, then prove its Windows Job Object
  // removes the MATLAB launcher/child before an explicit backend restart.
  await input('pause(30);');
  await waitFor(async () => (await page.locator('.session-state').textContent()).includes('running'), 'crash fixture starts');
  const pythonQuery = `@(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object { $_.CommandLine -like '*${fixture}*' }).ProcessId`;
  const { stdout: pythonPid } = await promisify(execFile)('pwsh', ['-NoProfile', '-Command', pythonQuery], { timeout: 15_000 });
  const supervisorPid = Number(pythonPid.trim().split(/\s+/).find(Boolean)); assert.ok(supervisorPid > 0);
  process.kill(supervisorPid);
  await waitFor(async () => {
    const { stdout } = await promisify(execFile)('pwsh', ['-NoProfile', '-Command', `@(Get-CimInstance Win32_Process -Filter "Name = 'MATLAB.exe'" | Where-Object { $_.CommandLine -like '*${fixture}*' }).ProcessId`], { timeout: 15_000 });
    return !stdout.trim();
  }, 'backend crash cleans owned MATLAB descendants', 15_000);
  await command('Backend: Restart Python Service');
  await waitFor(async () => (await page.locator('#output').textContent()).includes('Python backend restarted'), 'backend restarts explicitly after crash');
  await command('Extensions: Activate Trusted Extension…');
  await page.getByText('MATLAB Session', { exact: false }).waitFor();
  await command('MATLAB: Command Window (Extension)');
  await page.getByRole('textbox', { name: 'MATLAB command', exact: true }).fill('firstparty_extension=1;');
  await page.getByRole('button', { name: 'Run command', exact: true }).click();
  job = await resultAfter(job); await variable('firstparty_extension', '1');
  await command('Extensions: Activate Trusted Extension…');
  await page.getByText('Simulink Results', { exact: false }).waitFor();
  // New UI model workflow: static open never starts MATLAB, parameter edit is
  // staged through the asynchronous batch job, and history is hash-guarded.
  await page.getByRole('treeitem', { name: 'rpc_model.slx', exact: true }).click();
  await page.getByRole('button', { name: 'Block Gain (Gain)', exact: true }).click();
  const beforeModelSha = await page.locator('.model-view').getAttribute('data-sha256');
  assert.ok(beforeModelSha);
  await page.getByRole('button', { name: 'Edit model parameter Gain', exact: true }).click();
  await page.getByRole('textbox', { name: 'Model parameter value', exact: true }).fill('4');
  await page.getByRole('button', { name: 'Apply and Save', exact: true }).click();
  await waitFor(async () => await page.locator('#model-results[data-state="finished"]').count() === 1, 'asynchronous model edit finishes', 180_000);
  await waitFor(async () => (await page.locator('.model-view').getAttribute('data-sha256')) !== beforeModelSha, 'edited model viewport reloads');
  const afterModelSha = await page.locator('.model-view').getAttribute('data-sha256');
  assert.ok(afterModelSha && afterModelSha !== beforeModelSha);
  await page.getByRole('button', { name: 'Undo model edit', exact: true }).click();
  await waitFor(async () => (await page.locator('.model-view').getAttribute('data-sha256')) === beforeModelSha, 'model undo restores exact source hash');
  await page.getByRole('button', { name: 'Redo model edit', exact: true }).click();
  await waitFor(async () => (await page.locator('.model-view').getAttribute('data-sha256')) === afterModelSha, 'model redo restores edited source hash');
  await page.getByRole('button', { name: 'Simulate…', exact: true }).click();
  await page.getByRole('textbox', { name: 'Simulation stop time', exact: true }).fill('1');
  await page.getByRole('button', { name: 'Run simulation', exact: true }).click();
  await waitFor(async () => {
    const text = await page.locator('#model-results').textContent();
    return await page.locator('#model-results[data-state="finished"]').count() === 1
      && text.includes('independent MATLAB batch')
      && text.includes('MATLAB 2026a');
  }, 'independent model simulation finishes', 180_000);
  assert.match(await page.locator('#model-results').textContent(), /MATLAB 2026a/);
  assert.equal(await page.locator('.model-view').getAttribute('data-sha256'), afterModelSha, 'simulation does not modify source model');
  const staleEdit = path.join(fixture, 'stale.slx'); await fs.copyFile(modelOutput.trim(), staleEdit);
  await fs.copyFile(staleEdit, path.join(workspace, 'rpc_model.slx'));
  await page.getByRole('button', { name: 'Edit and Save…', exact: true }).click();
  await page.getByRole('button', { name: 'Apply and Save', exact: true }).click();
  await waitFor(async () => (await page.locator('#output').textContent()).includes('source model changed'), 'external model conflict is reported without overwrite');
  console.log('PASS: real R2026a + Electron command stream, variable edit, file/section shared session, rendered figure, diagnostic navigation, cancellation/no replay, staged model edit/undo/redo, independent simulation and conflict guard.');
} catch (error) {
  if (page && !page.isClosed()) {
    console.error(await page.locator('body').ariaSnapshot());
    console.error('Console:', await page.locator('#output').textContent());
    console.error('Result:', await page.locator('#matlab-results').textContent());
    const id = await page.locator('#matlab-results').getAttribute('data-job-id');
    if (id) console.error('Run status:', JSON.stringify(await page.evaluate(async id => {
      const reply = await window.slx.matlabRunStatus(id);
      if (reply.ok && reply.value.result) delete reply.value.result.figures;
      return reply;
    }, id)));
  }
  throw error;
} finally {
  await application?.evaluate(({ BrowserWindow }) => { for (const window of BrowserWindow.getAllWindows()) window.destroy(); }).catch(() => {});
  await application?.close().catch(() => {});
  console.log(`Real MATLAB desktop fixtures: ${fixture}`);
}

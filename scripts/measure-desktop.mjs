// Repeatable local M1 measurement. This records Electron-owned metrics only;
// the Python child is reported separately rather than hidden in a browser total.
import * as fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import { _electron as electron } from 'playwright';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(import.meta.url);
const fixture = await fs.mkdtemp(path.join(os.tmpdir(), 'slx-desktop-measure-'));
const workspace = path.join(fixture, 'workspace');
await fs.mkdir(workspace);
await fs.writeFile(path.join(workspace, 'measure.m'), 'value = 1;\n');
const runs = [];
let idleOwnedProcesses = null;
const psOwned = String.raw`
$taskRootPid = [int]$env:SLX_MEASURE_ROOT_PID
$taskProcesses = @(Get-CimInstance Win32_Process)
$taskOwned = [Collections.Generic.HashSet[int]]::new()
[void]$taskOwned.Add($taskRootPid)
do {
  $taskAdded = $false
  foreach ($item in $taskProcesses) {
    if ($taskOwned.Contains([int]$item.ParentProcessId) -and $taskOwned.Add([int]$item.ProcessId)) { $taskAdded = $true }
  }
} while ($taskAdded)
@(foreach ($taskPid in $taskOwned) {
  $item = Get-Process -Id $taskPid -ErrorAction SilentlyContinue
  if ($item) { [pscustomobject]@{pid=$item.Id;name=$item.ProcessName;privateBytes=$item.PrivateMemorySize64;workingSetBytes=$item.WorkingSet64} }
}) | ConvertTo-Json -Compress
`;
for (let index = 0; index < 10; index += 1) {
  const start = performance.now();
  const env = { ...process.env, SLX_DESKTOP_TEST_HIDE: '1', SLX_DESKTOP_STATE_DIR: path.join(fixture, 'state', String(index)), SLX_DESKTOP_WORKSPACE: workspace };
  delete env.ELECTRON_RUN_AS_NODE;
  const application = await electron.launch({ executablePath: require('electron'), args: [path.join(root, 'dist/desktop/electron/main.cjs')], cwd: root, env, chromiumSandbox: true, timeout: 30_000 });
  try {
  const page = await application.firstWindow();
  page.setDefaultTimeout(10_000);
  await page.locator('body[data-ready="true"]').waitFor();
  await application.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].showInactive());
  await page.getByRole('treeitem', { name: 'measure.m', exact: true }).click();
  await page.locator('.monaco-editor').waitFor();
  await page.getByRole('tab', { name: 'measure.m', exact: true }).click();
  await page.keyboard.press('Control+End');
  await page.keyboard.insertText('% input probe');
  await page.locator('[role="tab"][aria-label="measure.m"]').filter({ hasText: '●' }).waitFor();
  const readyMs = performance.now() - start;
  // Electron MemoryInfo uses KiB despite its historical privateBytes field name.
  const metrics = await application.evaluate(({ app }) => app.getAppMetrics().map(metric => ({ pid: metric.pid, type: metric.type, privateKiB: metric.memory.privateBytes ?? null, workingSetKiB: metric.memory.workingSetSize ?? null })));
  runs.push({ run: index + 1, readyMs: Math.round(readyMs * 100) / 100, metrics });
  if (index === 0 && process.platform === 'win32') {
    console.log('Sampling all owned processes 30 seconds after editor readiness…');
    await new Promise(resolve => setTimeout(resolve, 30_000));
    idleOwnedProcesses = JSON.parse(execFileSync('pwsh', ['-NoProfile', '-Command', psOwned], { encoding: 'utf8', env: { ...process.env, SLX_MEASURE_ROOT_PID: String(application.process().pid) }, windowsHide: true }));
  }
  } finally {
  await application.evaluate(({ BrowserWindow }) => { for (const window of BrowserWindow.getAllWindows()) window.destroy(); }).catch(() => {});
  await application.close().catch(() => {});
  }
}
const sortedTimes = runs.map(run => run.readyMs).sort((a, b) => a - b);
const electronPrivateKiB = runs.map(run => run.metrics.reduce((sum, metric) => sum + (metric.privateKiB ?? 0), 0));
const report = {
  generatedAt: new Date().toISOString(),
  commit: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim(),
  dirty: Boolean(execFileSync('git', ['status', '--porcelain'], { cwd: root, encoding: 'utf8' }).trim()),
  platform: `${process.platform} ${os.release()} ${os.arch()}`,
  cpu: os.cpus()[0]?.model,
  ramGiB: Math.round(os.totalmem() / 1024 ** 3),
  node: process.version,
  electron: JSON.parse(await fs.readFile(path.join(root, 'node_modules/electron/package.json'), 'utf8')).version,
  workspace: 'generated: one 1-line .m file; warm OS cache after first run',
  measurementMode: 'Minified development bundle, Electron with Playwright instrumentation; fresh processes, OS disk cache not flushed. Antivirus context not controlled.',
  runs,
  idleOwnedProcesses,
  summary: {
    medianReadyMs: (sortedTimes[4] + sortedTimes[5]) / 2,
    maxReadyMs: Math.max(...runs.map(run => run.readyMs)),
    maxElectronPrivateMiBAtReady: Math.max(...electronPrivateKiB) / 1024,
    ownedPrivateMiBAt30s: idleOwnedProcesses?.reduce((sum, item) => sum + item.privateBytes, 0) / 1024 ** 2 || null,
    note: 'Ready-time Electron metrics exclude Python. The 30-second Windows process-tree snapshot includes the owned Python RPC child; unrelated processes are excluded.'
  }
};
const output = path.join(root, 'output/measurements');
await fs.mkdir(output, { recursive: true });
await fs.writeFile(path.join(output, 'desktop-m2-foundation.json'), `${JSON.stringify(report, null, 2)}\n`);
console.log(JSON.stringify(report.summary));
console.log(`Wrote ${path.join(output, 'desktop-m2-foundation.json')}`);

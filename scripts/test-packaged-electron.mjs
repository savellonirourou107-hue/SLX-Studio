// Smoke-test the actual portable Windows directory produced by package:electron.
import assert from 'node:assert/strict';
import * as fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { _electron as electron } from 'playwright';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const executable = path.join(root, 'release', 'SLXStudio-win32-x64', 'SLXStudio.exe');
await fs.stat(executable);
const fixture = await fs.mkdtemp(path.join(os.tmpdir(), 'slx-packaged-'));
const workspace = path.join(fixture, 'workspace');
await fs.mkdir(workspace);
await fs.writeFile(path.join(workspace, 'packaged.m'), 'value = 1;\n');
const env = { ...process.env, SLX_DESKTOP_TEST_HIDE: '1', SLX_DESKTOP_STATE_DIR: path.join(fixture, 'state'), SLX_DESKTOP_WORKSPACE: workspace, SLX_STUDIO_PYTHON: process.env.SLX_STUDIO_PYTHON || 'python' };
delete env.ELECTRON_RUN_AS_NODE;
let application;
try {
  application = await electron.launch({ executablePath: executable, args: [], cwd: path.dirname(executable), env, chromiumSandbox: true, timeout: 30_000 });
  const page = await application.firstWindow();
  page.setDefaultTimeout(15_000);
  await page.locator('body[data-ready="true"]').waitFor();
  assert.equal(await page.evaluate(() => typeof window.process), 'undefined');
  await page.getByRole('treeitem', { name: 'packaged.m', exact: true }).waitFor();
  console.log('PASS: packaged Electron executable launches, isolates renderer, and opens a workspace.');
} finally {
  await application?.close().catch(() => {});
  await fs.rm(fixture, { recursive: true, force: true });
}

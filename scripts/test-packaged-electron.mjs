// Smoke-test the actual portable Windows directory produced by package:electron.
import assert from 'node:assert/strict';
import * as fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { _electron as electron } from 'playwright';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const executable = path.resolve(process.env.SLX_DESKTOP_PACKAGED_EXE || path.join(root, 'release', 'SLXStudio-win32-x64', 'SLXStudio.exe'));
await fs.stat(executable);
const fixture = await fs.mkdtemp(path.join(os.tmpdir(), 'slx-packaged-'));
const workspace = path.join(fixture, 'workspace');
await fs.mkdir(workspace);
await fs.writeFile(path.join(workspace, 'packaged.m'), 'value = 1;\n');
const env = { ...process.env, SLX_DESKTOP_TEST_HIDE: '1', SLX_DESKTOP_STATE_DIR: path.join(fixture, 'state'), SLX_DESKTOP_WORKSPACE: workspace, SLX_STUDIO_PYTHON: process.env.SLX_STUDIO_PYTHON || 'python' };
delete env.ELECTRON_RUN_AS_NODE;
let application;
try {
  for (let launch = 0; launch < 2; launch += 1) {
    application = await electron.launch({ executablePath: executable, args: [], cwd: path.dirname(executable), env, chromiumSandbox: true, timeout: 30_000 });
    const page = await application.firstWindow();
    page.setDefaultTimeout(15_000);
    await page.locator('body[data-ready="true"]').waitFor();
    assert.equal(await page.evaluate(() => typeof window.process), 'undefined');
    await page.getByRole('treeitem', { name: 'packaged.m', exact: true }).click();
    await page.getByRole('tab', { name: 'packaged.m', exact: true }).click();
    if (launch === 0) {
      await page.keyboard.press('Control+End');
      await page.keyboard.insertText('% installed round-trip\n');
      await page.keyboard.press('Control+s');
      await page.locator('[role="tab"][aria-label="packaged.m"]').filter({ hasText: '●' }).waitFor({ state: 'hidden' });
      assert.match(await fs.readFile(path.join(workspace, 'packaged.m'), 'utf8'), /installed round-trip/);
      const extension = await page.evaluate(async () => {
        const listed = await window.slx.extensionsList();
        if (!listed.ok) throw new Error(listed.error);
        const activated = await window.slx.extensionsActivate('sample.hello');
        if (!activated.ok) throw new Error(activated.error);
        const result = await window.slx.extensionsExecute('sample.hello', 'sample.hello');
        const stopped = await window.slx.extensionsDeactivate('sample.hello');
        if (!stopped.ok) throw new Error(stopped.error);
        return result;
      });
      assert.equal(extension.ok, true, 'the installed extension host must run from packaged resources');
    } else {
      assert.match(await page.locator('#monaco').textContent(), /installed\s+round-trip/, 'saved content survives close and reopen');
    }
    await application.close();
    application = undefined;
  }
  console.log('PASS: packaged executable isolates the renderer, saves a file, runs its extension host, and reopens with saved content.');
} finally {
  await application?.close().catch(() => {});
  await fs.rm(fixture, { recursive: true, force: true });
}

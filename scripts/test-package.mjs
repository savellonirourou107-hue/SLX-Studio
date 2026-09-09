import assert from 'node:assert/strict';
import { test } from 'node:test';
import * as fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { packageElectronWindows } from './package-electron.mjs';

test('Windows packaging resolves a lazy Electron runtime before copying and preserves other artifacts', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'slx-package-unit-'));
  try {
    await fs.mkdir(path.join(root, 'dist/desktop/src'), { recursive: true });
    await fs.writeFile(path.join(root, 'dist/desktop/package.json'), '{"main":"electron/main.cjs"}');
    await fs.writeFile(path.join(root, 'dist/desktop/src/backend.py'), '# packaged backend');
    await fs.mkdir(path.join(root, 'release'), { recursive: true });
    await fs.writeFile(path.join(root, 'release/keep.zip'), 'unrelated artifact');
    const executable = path.join(root, 'node_modules/electron/dist/electron.exe');
    let resolutions = 0;
    const output = await packageElectronWindows({
      projectRoot: root,
      loadElectron: async () => {
        resolutions += 1;
        await fs.mkdir(path.dirname(executable), { recursive: true });
        await fs.writeFile(executable, 'fake runtime: no executable code');
        return executable;
      },
    });
    assert.equal(resolutions, 1);
    assert.equal(await fs.readFile(path.join(output, 'SLXStudio.exe'), 'utf8'), 'fake runtime: no executable code');
    assert.equal(await fs.readFile(path.join(output, 'resources/app/src/backend.py'), 'utf8'), '# packaged backend');
    assert.equal(await fs.readFile(path.join(root, 'release/keep.zip'), 'utf8'), 'unrelated artifact');
    await assert.rejects(packageElectronWindows({ projectRoot: root, loadElectron: () => path.join(root, 'missing/electron.exe') }), /ENOENT/);
    assert.ok((await fs.stat(path.join(output, 'SLXStudio.exe'))).isFile(), 'a missing runtime must not destroy the prior package');
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});

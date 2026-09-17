import assert from 'node:assert/strict';
import { test } from 'node:test';
import * as fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

async function loadBackend() {
  const result = await build({
    entryPoints: [path.join(root, 'apps/desktop/electron/backend.ts')],
    bundle: true,
    platform: 'node',
    format: 'esm',
    write: false,
  });
  return import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`);
}

const { PythonBackend } = await loadBackend();

test('Python backend bounds queued request bytes when its child stops consuming stdin', { timeout: 10_000 }, async () => {
  const fixture = await fs.mkdtemp(path.join(os.tmpdir(), 'slx-backpressure-'));
  const packageDir = path.join(fixture, 'slxdiff');
  await fs.mkdir(packageDir, { recursive: true });
  await fs.writeFile(path.join(packageDir, '__init__.py'), '');
  await fs.writeFile(path.join(packageDir, 'rpc.py'), 'import time\ntime.sleep(60)\n');

  const backend = new PythonBackend(
    process.env.SLX_STUDIO_PYTHON || 'python',
    fixture,
    fixture,
    path.join(fixture, 'state'),
  );
  const large = 'x'.repeat(12 * 1024 * 1024);
  const first = backend.request('blocked', { large });
  const second = backend.request('blocked', { large });
  await assert.rejects(
    backend.request('blocked', { large }),
    /write queue exceeded/,
    'a stalled child must not allow unbounded Node stdin buffering',
  );

  backend.close();
  await Promise.allSettled([first, second]);
  await fs.rm(fixture, { recursive: true, force: true });
});

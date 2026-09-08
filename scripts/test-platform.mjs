import assert from 'node:assert/strict';
import { test } from 'node:test';
import * as fs from 'node:fs/promises';
import { once } from 'node:events';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
async function loadTypeScript(relative) {
  const result = await build({ entryPoints: [path.join(root, relative)], bundle: true, platform: 'node', format: 'esm', write: false });
  return import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`);
}
const { FrameDecoder, PythonBackend } = await loadTypeScript('apps/desktop/electron/backend.ts');
const { CommandRegistry } = await loadTypeScript('packages/commands/index.ts');
const frame = value => {
  const payload = Buffer.from(JSON.stringify(value));
  return Buffer.concat([Buffer.from(`Content-Length: ${payload.length}\r\n\r\n`), payload]);
};

test('frame decoder handles split/coalesced frames and Unicode byte lengths', () => {
  const decoder = new FrameDecoder();
  const values = [{ id: 1, result: '控制工程' }, { id: 2, result: [1, 2, 3] }];
  const bytes = Buffer.concat(values.map(frame));
  const found = [];
  for (const byte of bytes) found.push(...decoder.feed(Buffer.from([byte])));
  assert.deepEqual(found, values);
  assert.deepEqual(new FrameDecoder().feed(bytes), values);
});

test('frame decoder rejects malformed, oversized and non-UTF8 responses', () => {
  for (const bytes of [
    Buffer.from('Content-Length: 2\r\nContent-Length: 2\r\n\r\n{}'),
    Buffer.from('Content-Length: 999999999\r\n\r\n'),
    Buffer.from('Content-Length: 0\r\n\r\n'),
    Buffer.alloc(4097, 65),
    Buffer.from('Content-Length: 1\r\n\r\nx'),
    Buffer.concat([Buffer.from('Content-Length: 1\r\n\r\n'), Buffer.from([255])]),
  ]) assert.throws(() => new FrameDecoder().feed(bytes));
});

test('command registry validates, shares handlers, checks enablement and disposes', async () => {
  const registry = new CommandRegistry();
  let called = 0;
  const definition = { id: 'file.save', title: 'File: Save', run: () => called++ };
  const dispose = registry.register(definition);
  definition.run = () => { throw new Error('mutated original'); };
  await registry.execute('file.save');
  assert.equal(called, 1);
  assert.throws(() => registry.register({ id: 'file.save', title: 'duplicate', run() {} }));
  for (const id of ['', 'file..save', 'file.', '.save', '../save']) assert.throws(() => registry.register({ id, title: 'Invalid', run() {} }));
  assert.throws(() => registry.register({ id: 'file.bad', title: '', run() {} }));
  registry.register({ id: 'file.disabled', title: 'Disabled', enabled: () => false, run() { throw new Error('must not execute'); } });
  await assert.rejects(registry.execute('file.disabled'), /unavailable/);
  dispose();
  dispose();
  await assert.rejects(registry.execute('file.save'), /Unknown command/);
});

test('real Python supervisor correlates requests, bounds pending work and never replays after close/crash', async () => {
  const fixture = await fs.mkdtemp(path.join(os.tmpdir(), 'slx-platform-'));
  const backend = new PythonBackend(process.env.SLX_STUDIO_PYTHON || 'python', fixture, root, path.join(fixture, 'state'));
  try {
    const jobs = Array.from({ length: 33 }, () => backend.request('initialize'));
    const results = await Promise.allSettled(jobs);
    assert.equal(results.filter(result => result.status === 'fulfilled').length, 32);
    assert.match(results[32].reason.message, /Too many pending/);
    assert.equal(results[0].value.matlab_started, false);
    await assert.rejects(backend.request('document/read', { relative: '../escape.m' }), /relative path/);
    assert.deepEqual((await backend.request('workspace/listDirectory')).items, []);
    // The private child is accessed only here to inject an owned-process crash.
    const exited = once(backend.child, 'exit');
    backend.child.kill();
    const pending = backend.request('initialize');
    await assert.rejects(pending, /exited|closed|EPIPE|write/i);
    await exited;
    await assert.rejects(backend.request('initialize'), /closed/);
  } finally {
    backend.close();
    await fs.rm(fixture, { recursive: true, force: true });
  }
});

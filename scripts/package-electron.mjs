// Build a self-contained Electron directory for Windows.  Python remains an
// external, user-configurable dependency; the package includes the pure
// Python source so the backend can be started with an installed Python.
import { cp, mkdir, rename, rm } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
process.chdir(root);
await rm('release', { recursive: true, force: true });
const output = path.join(root, 'release', 'SLXStudio-win32-x64');
await mkdir(output, { recursive: true });
// The Electron npm package already contains the exact Windows runtime. Copying
// it directly avoids a second download and keeps packaging reproducible in
// offline/air-gapped contributor environments.
await cp(path.join(root, 'node_modules/electron/dist'), output, { recursive: true });
await rename(path.join(output, 'electron.exe'), path.join(output, 'SLXStudio.exe'));
await mkdir(path.join(output, 'resources/app'), { recursive: true });
await cp(path.join(root, 'dist/desktop'), path.join(output, 'resources/app'), { recursive: true });
console.log(`Electron Windows package: ${output}`);

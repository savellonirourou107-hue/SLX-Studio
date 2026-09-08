// Build a self-contained Electron directory for Windows.  Python remains an
// external, user-configurable dependency; the package includes the pure
// Python source so the backend can be started with an installed Python.
import { cp, mkdir, rename, rm, stat } from 'node:fs/promises';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(import.meta.url);

export async function packageElectronWindows({ projectRoot = root, loadElectron = () => require('electron') } = {}) {
  // Electron 44 installs its binary lazily. Resolve through the package's public
  // entry point before using dist; npm ci alone does not create that directory.
  // A populated Electron cache is reused without a second runtime download.
  const executable = path.resolve(await loadElectron());
  if (path.basename(executable).toLowerCase() !== 'electron.exe') throw new Error('Packaging requires the Windows Electron runtime');
  await stat(executable);
  const appSource = path.join(path.resolve(projectRoot), 'dist/desktop');
  await stat(path.join(appSource, 'package.json'));
  const output = path.join(path.resolve(projectRoot), 'release', 'SLXStudio-win32-x64');
  // Rebuild only this generated package; preserve unrelated release artifacts.
  await rm(output, { recursive: true, force: true });
  await mkdir(output, { recursive: true });
  await cp(path.dirname(executable), output, { recursive: true });
  await rename(path.join(output, 'electron.exe'), path.join(output, 'SLXStudio.exe'));
  await mkdir(path.join(output, 'resources/app'), { recursive: true });
  await cp(appSource, path.join(output, 'resources/app'), { recursive: true });
  return output;
}

if (process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url) {
  console.log(`Electron Windows package: ${await packageElectronWindows()}`);
}

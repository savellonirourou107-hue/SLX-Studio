import './style.css';
import { CommandRegistry } from '../../../packages/commands';
import { ConfigurationStore } from '../../../packages/configuration';
import { DesktopServices } from '../../../packages/core/services';
import { DocumentEditors } from '../../../packages/editor/documents';
import { CustomEditorRegistry } from '../../../packages/editor/registry';
import { OutputService, ViewRegistry } from '../../../packages/workbench';
import type { WorkspaceInfo } from '../../../packages/protocol';

const element = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const files = new DesktopServices(window.slx);
const commands = new CommandRegistry();
const configuration = new ConfigurationStore([
  { key: 'editor.fontSize', defaultValue: 14, validate: (value): value is number => typeof value === 'number' && Number.isInteger(value) && value >= 10 && value <= 32 },
  { key: 'editor.minimap', defaultValue: false, validate: (value): value is boolean => typeof value === 'boolean' },
  { key: 'workspace.explorer.pageSize', defaultValue: 512, validate: (value): value is number => value === 512, workspaceWritable: true },
  { key: 'security.trust', defaultValue: false, validate: (value): value is boolean => typeof value === 'boolean', sensitive: true },
]);
const views = new ViewRegistry();
views.register({ id: 'workbench.explorer', title: 'Explorer', location: 'sidebar' });
views.register({ id: 'workbench.output', title: 'Output', location: 'panel' });
const outputService = new OutputService();
const editorRegistry = new CustomEditorRegistry();
const output = element('output');
let workspace: WorkspaceInfo | null = null;
let closing = false;
let explorerGeneration = 0;
function log(message: string): void {
  outputService.append(message);
  output.textContent = outputService.snapshot().map(entry => entry.text).join('\n').slice(-65_536);
  output.scrollTop = output.scrollHeight;
}
function report(error: unknown): void { log((error as Error).message || String(error)); }
let decisionQueue: Promise<unknown> = Promise.resolve();
function decide(title: string, detail: string, options: string[]): Promise<string> {
  const job = decisionQueue.then(() => new Promise<string>(resolve => {
    const dialog = element<HTMLDialogElement>('decision');
    element('decision-title').textContent = title;
    element('decision-text').textContent = detail;
    const finish = (value: string) => { dialog.close(); dialog.oncancel = null; resolve(value); };
    element('decision-actions').replaceChildren(...options.map(option => {
      const button = document.createElement('button');
      button.textContent = option;
      button.onclick = () => finish(option);
      return button;
    }));
    dialog.oncancel = event => { event.preventDefault(); finish('Cancel'); };
    dialog.showModal();
  }));
  decisionQueue = job.catch(() => {});
  return job;
}
const editors = new DocumentEditors(element('monaco'), files, decide, renderEditors, log);
editorRegistry.register({ id: 'editor.matlabText', label: 'MATLAB text', extensions: ['.m'], open: path => editors.open(path) });
let lastTabSignature = '';
function renderEditors(): void {
  const signature = [...editors.documents.values()].map(document => `${document.path}|${editors.dirty(document)}|${editors.active === document}`).join('\n');
  if (signature !== lastTabSignature) {
    lastTabSignature = signature;
    element('tabs').replaceChildren(...[...editors.documents.values()].map(opened => {
      const wrapper = document.createElement('div');
      wrapper.className = `tab-wrap${editors.active === opened ? ' active' : ''}`;
      const tab = document.createElement('button');
      tab.className = 'tab-select';
      tab.role = 'tab';
      tab.setAttribute('aria-selected', String(editors.active === opened));
      tab.setAttribute('aria-label', opened.path);
      tab.textContent = `${opened.path.split('/').pop()}${editors.dirty(opened) ? ' ●' : ''}`;
      tab.onclick = () => editors.select(opened.path);
      const close = document.createElement('button');
      close.className = 'tab-close'; close.textContent = '×';
      close.setAttribute('aria-label', `Close ${opened.path}`);
      close.onclick = () => void editors.close(opened.path).catch(report);
      wrapper.append(tab, close);
      return wrapper;
    }));
  }
  element('welcome').hidden = editors.documents.size > 0;
  element('breadcrumbs').textContent = editors.active?.path.replaceAll('/', '  ›  ') || 'Workspace';
  element('document-status').textContent = editors.position();
}
async function directory(parent: HTMLElement, relative: string, cursor: number, generation: number): Promise<void> {
  const page = await files.list(relative, cursor);
  if (generation !== explorerGeneration) return;
  for (const item of page.items) {
    const row = document.createElement('button');
    row.className = `tree-row ${item.kind === 'directory' ? 'directory' : ''}`;
    row.role = 'treeitem'; row.setAttribute('aria-label', item.path);
    const icon = document.createElement('span'); icon.textContent = item.kind === 'directory' ? '›' : item.kind === 'm' ? 'M' : '▦'; icon.setAttribute('aria-hidden', 'true');
    row.append(icon, document.createTextNode(item.name));
    parent.append(row);
    if (item.kind === 'directory') {
      const children = document.createElement('div'); children.className = 'tree-children'; children.role = 'group'; children.hidden = true;
      parent.append(children);
      let loaded = false;
      row.setAttribute('aria-expanded', 'false');
      row.onclick = async () => {
        children.hidden = !children.hidden;
        row.setAttribute('aria-expanded', String(!children.hidden)); icon.textContent = children.hidden ? '›' : '⌄';
        if (!loaded && !children.hidden) { loaded = true; try { await directory(children, item.path, 0, generation); } catch (error) { loaded = false; report(error); } }
      };
    } else row.onclick = () => { const editor = editorRegistry.resolve(item.path); if (editor) void Promise.resolve(editor.open(item.path)).catch(report); else log(`${item.path}: no registered editor in this desktop. Use the legacy Workbench; the SLX viewport is an M3 deliverable.`); };
  }
  if (page.next_cursor !== null) {
    const more = document.createElement('button'); more.className = 'tree-more'; more.textContent = 'Load more entries…';
    more.onclick = async () => { more.disabled = true; try { await directory(parent, relative, page.next_cursor!, generation); more.remove(); } catch (error) { more.disabled = false; report(error); } };
    parent.append(more);
  }
  if (page.truncated) log(`${relative || 'Root'} listing reached the safety limit; open a narrower workspace.`);
}
async function refresh(): Promise<void> {
  const generation = ++explorerGeneration;
  element('tree').replaceChildren();
  if (workspace) await directory(element('tree'), '', 0, generation);
}
async function setWorkspace(info: WorkspaceInfo): Promise<void> {
  workspace = info;
  element('workspace-name').textContent = info.root.split(/[\\/]/).pop()?.toUpperCase() || info.root;
  element('workspace-name').title = info.root;
  element('workspace-status').textContent = info.root;
  await refresh();
  if (info.initial_file?.endsWith('.m')) await editors.open(info.initial_file);
}
const palette = element<HTMLDialogElement>('palette');
function commandResults(): void {
  const query = element<HTMLInputElement>('command-search').value.toLowerCase().replace(/^>\s*/, '');
  element('command-results').replaceChildren(...commands.list().filter(command => command.id !== 'workbench.palette' && command.title.toLowerCase().includes(query)).map(command => {
    const button = document.createElement('button'); button.textContent = command.title;
    button.disabled = command.enabled ? !command.enabled() : false;
    button.onclick = () => { palette.close(); void commands.execute(command.id).catch(report); };
    return button;
  }));
}
commands.register({ id: 'workspace.open', title: 'Workspace: Open Folder…', run: async () => {
  if (!await editors.closeAll()) return;
  const selected = await files.chooseWorkspace();
  if (selected) await setWorkspace(selected);
} });
commands.register({ id: 'workspace.refresh', title: 'Workspace: Refresh Explorer', enabled: () => !!workspace, run: refresh });
commands.register({ id: 'file.save', title: 'File: Save', enabled: () => !!editors.active, run: () => editors.save() });
commands.register({ id: 'file.reload', title: 'File: Reload from Disk', enabled: () => !!editors.active, run: () => editors.reload() });
commands.register({ id: 'settings.show', title: 'Settings: Show Effective Configuration', run: () => log(JSON.stringify(configuration.effective(), null, 2)) });
commands.register({ id: 'file.close', title: 'File: Close Editor', enabled: () => !!editors.active, run: () => editors.active && editors.close(editors.active.path) });
commands.register({ id: 'workbench.palette', title: 'Workbench: Command Palette', run: () => {
  element<HTMLInputElement>('command-search').value = ''; commandResults(); palette.showModal(); element('command-search').focus();
} });
element('command-search').addEventListener('input', commandResults);
element('command-search').addEventListener('keydown', event => { if (event.key === 'Enter') element('command-results').querySelector<HTMLButtonElement>('button:not(:disabled)')?.click(); });
document.querySelectorAll<HTMLButtonElement>('[data-command]').forEach(button => button.onclick = () => void commands.execute(button.dataset.command!).catch(report));
window.slx.onCommand(id => void commands.execute(id).catch(report));
window.slx.onClose(() => {
  if (closing) return;
  closing = true;
  void editors.closeAll().then(ok => { if (ok) window.slx.confirmClose(); }).catch(report).finally(() => { closing = false; });
});
window.addEventListener('keydown', event => {
  if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
  const id = event.key.toLowerCase() === 's' ? 'file.save' : event.key.toLowerCase() === 'w' ? 'file.close' : event.shiftKey && event.key.toLowerCase() === 'p' ? 'workbench.palette' : '';
  if (id && !element<HTMLDialogElement>('decision').open) { event.preventDefault(); event.stopPropagation(); void commands.execute(id).catch(report); }
}, true);
element('clear-output').onclick = () => { outputService.clear(); output.textContent = ''; };
void files.workspace().then(async info => {
  if (info) await setWorkspace(info);
  document.body.dataset.ready = 'true';
}).catch(report);

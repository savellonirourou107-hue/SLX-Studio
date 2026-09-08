import './style.css';
import { CommandRegistry } from '../../../packages/commands';
import { ConfigurationStore, DESKTOP_SCHEMAS } from '../../../packages/configuration';
import { DesktopServices } from '../../../packages/core/services';
import { DocumentEditors } from '../../../packages/editor/documents';
import { CustomEditorRegistry } from '../../../packages/editor/registry';
import { ModelEditors } from '../../../packages/model/view';
import { OutputService, ProblemsService, ViewRegistry, WorkbenchContributionRegistry } from '../../../packages/workbench';
import type { Problem } from '../../../packages/workbench';
import { unwrap } from '../../../packages/protocol';
import type { ExtensionRecord, MatlabJobStatus, MatlabRuntimeStatus, ModelViewport, WorkspaceInfo } from '../../../packages/protocol';
import { SettingsController } from './settings';

const element = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const files = new DesktopServices(window.slx);
const commands = new CommandRegistry();
const configuration = new ConfigurationStore(DESKTOP_SCHEMAS);
const views = new ViewRegistry();
const outputService = new OutputService();
const problemsService = new ProblemsService();
const editorRegistry = new CustomEditorRegistry();
const output = element('output');
let workspace: WorkspaceInfo | null = null;
let activeKind: 'text' | 'model' = 'text';
const modelProblems = new Map<string, Problem[]>();
let closing = false;
let explorerGeneration = 0;
let matlabJob: { kind: 'command' | 'run'; id: string; stdoutOffset: number; stderrOffset: number } | null = null;
const activeExtensions = new Map<string, { record: ExtensionRecord; remove: () => void }>();
function log(message: string): void {
  outputService.append(message);
  output.textContent = outputService.snapshot().map(entry => entry.text).join('\n').slice(-65_536);
  output.scrollTop = output.scrollHeight;
}
function report(error: unknown): void { log((error as Error).message || String(error)); }
function renderMatlabStatus(status: MatlabRuntimeStatus): void {
  const label = status.state === 'ready' ? 'MATLAB ready · persistent session' : status.available ? 'MATLAB stopped · opt-in' : 'MATLAB unavailable';
  document.querySelector<HTMLElement>('.session-state')!.textContent = matlabJob ? `MATLAB ${matlabJob.kind} running` : label;
  element('document-status').textContent = matlabJob ? `MATLAB ${matlabJob.kind} running` : status.state === 'ready' ? 'MATLAB session ready' : 'Ready';
}
async function refreshMatlabStatus(): Promise<MatlabRuntimeStatus | null> {
  if (!workspace) return null;
  const status = unwrap(await window.slx.matlabStatus());
  renderMatlabStatus(status);
  return status;
}
function matlabResultSummary(kind: 'command' | 'run', status: MatlabJobStatus): void {
  const result = status.result;
  if (!result) return;
  if (result.error?.message) {
    const problemPath = result.error.file || result.path || result.command || 'MATLAB';
    const problem: Problem = { path: problemPath, message: result.error.message, severity: 'error', line: result.error.line || undefined, source: 'MATLAB' };
    modelProblems.set(`matlab:${kind}:${status.id}`, [problem]);
    problemsService.replace([...modelProblems.values()].flat());
    log(`MATLAB ${kind} failed: ${result.error.message}`);
  } else {
    const variables = result.variables?.length || 0;
    const figures = result.figures?.length || 0;
    log(`MATLAB ${kind} finished${result.elapsed_seconds ? ` in ${result.elapsed_seconds.toFixed(2)}s` : ''} · ${variables} variables · ${figures} figures${result.state_lost ? ' · session state discarded' : ''}.`);
  }
  if (result.debug_events?.length) log(`MATLAB tracepoints: ${result.debug_events.map(event => `${event.file}:${event.line}`).join(', ')}`);
}
async function pollMatlabJob(): Promise<void> {
  const current = matlabJob;
  if (!current) return;
  try {
    const status = current.kind === 'command'
      ? unwrap(await window.slx.matlabCommandStatus(current.id, current.stdoutOffset, current.stderrOffset))
      : unwrap(await window.slx.matlabRunStatus(current.id, current.stdoutOffset, current.stderrOffset));
    current.stdoutOffset = status.stdout_offset;
    current.stderrOffset = status.stderr_offset;
    if (status.stdout_delta) log(status.stdout_delta.replace(/\n$/, ''));
    if (status.stderr_delta) log(`[stderr] ${status.stderr_delta.replace(/\n$/, '')}`);
    if (status.state === 'running') { window.setTimeout(() => void pollMatlabJob(), 90); return; }
    matlabJob = null;
    matlabResultSummary(current.kind, status);
    await refreshMatlabStatus();
  } catch (error) { matlabJob = null; report(error); }
}
async function startMatlabCommand(command: string): Promise<void> {
  if (matlabJob) throw new Error('A MATLAB job is already active');
  const status = unwrap(await window.slx.matlabStartCommand(command));
  matlabJob = { kind: 'command', id: status.id, stdoutOffset: status.stdout_offset, stderrOffset: status.stderr_offset };
  log(`MATLAB command started: ${command}`);
  await refreshMatlabStatus();
  void pollMatlabJob();
}
async function startMatlabRun(path: string): Promise<void> {
  if (matlabJob) throw new Error('A MATLAB job is already active');
  const status = unwrap(await window.slx.matlabStartRun(path));
  matlabJob = { kind: 'run', id: status.id, stdoutOffset: status.stdout_offset, stderrOffset: status.stderr_offset };
  log(`MATLAB script started: ${path}`);
  const runtime = await refreshMatlabStatus(); if (runtime) renderMatlabStatus(runtime);
  void pollMatlabJob();
}
function requestMatlabCommand(): Promise<string | null> {
  const dialog = element<HTMLDialogElement>('matlab-command');
  const input = element<HTMLInputElement>('matlab-command-input');
  const run = element<HTMLButtonElement>('matlab-command-run');
  const cancel = element<HTMLButtonElement>('matlab-command-cancel');
  return new Promise(resolve => {
    const finish = (value: string | null) => { dialog.close(); run.onclick = null; cancel.onclick = null; dialog.oncancel = null; input.onkeydown = null; resolve(value); };
    run.onclick = () => finish(input.value.trim() || null);
    cancel.onclick = () => finish(null);
    dialog.oncancel = event => { event.preventDefault(); finish(null); };
    input.onkeydown = event => { if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); finish(input.value.trim() || null); } };
    input.value = ''; dialog.showModal(); input.focus();
  });
}
function requestModelEdit(): Promise<Readonly<Record<string, unknown>> | null> {
  const dialog = element<HTMLDialogElement>('matlab-command');
  const title = element('matlab-command-title');
  const help = dialog.querySelector<HTMLElement>('.dialog-help')!;
  const input = element<HTMLInputElement>('matlab-command-input');
  const run = element<HTMLButtonElement>('matlab-command-run');
  const cancel = element<HTMLButtonElement>('matlab-command-cancel');
  const previousTitle = title.textContent || '';
  const previousHelp = help.textContent || '';
  return new Promise(resolve => {
    const finish = (value: Readonly<Record<string, unknown>> | null) => { dialog.close(); title.textContent = previousTitle; help.textContent = previousHelp; run.onclick = null; cancel.onclick = null; dialog.oncancel = null; input.onkeydown = null; resolve(value); };
    run.onclick = () => {
      try {
        const value = JSON.parse(input.value);
        if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Edit must be a JSON object');
        finish(value as Readonly<Record<string, unknown>>);
      } catch (error) { log(`Invalid model edit JSON: ${(error as Error).message}`); }
    };
    cancel.onclick = () => finish(null);
    dialog.oncancel = event => { event.preventDefault(); finish(null); };
    input.onkeydown = event => { if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); run.click(); } };
    title.textContent = 'Apply Simulink model edit';
    help.textContent = 'Validated JSON is applied in MATLAB/Simulink and saved in place. The source SHA-256 is required.';
    input.value = '{"schema_version":"0.1","model_name":"","source_sha256":"…","operations":[]}'; dialog.showModal(); input.focus(); input.select();
  });
}
function renderExtensionViews(): void {
  const target = element('extension-views');
  const views = [...activeExtensions.values()].flatMap(item => item.record.contributes.views.map(view => ({ ...view, extension: item.record.id })));
  target.replaceChildren(...(views.length ? [Object.assign(document.createElement('div'), { className: 'extension-view-heading', textContent: 'EXTENSIONS' })] : []), ...views.map(view => {
    const panel = document.createElement('div'); panel.className = 'extension-view'; panel.textContent = view.title;
    panel.append(Object.assign(document.createElement('small'), { textContent: `${view.extension} · ${view.location}` })); return panel;
  }));
}
async function listExtensions(): Promise<readonly ExtensionRecord[]> {
  return unwrap(await window.slx.extensionsList());
}
async function activateExtension(id: string): Promise<void> {
  if (activeExtensions.has(id)) return;
  const record = unwrap(await window.slx.extensionsActivate(id));
  const contributionId = `extension.${id}`;
  const remove = contributions.register({
    id: contributionId,
    activate(context) {
      for (const command of record.contributes.commands) {
        context.add(commands.register({ id: command.command, title: command.title, run: async () => {
          try {
            const result = unwrap(await window.slx.extensionsExecute(id, command.command, {}));
            log(`${command.title}: ${typeof result === 'string' ? result : JSON.stringify(result)}`);
          } catch (error) {
            // A dead/timed-out host must not leave stale UI contributions active.
            await deactivateExtension(id).catch(() => {});
            throw error;
          }
        } }));
      }
      for (const view of record.contributes.views) context.add(views.register(view));
      for (const editor of record.contributes.editors) context.add(editorRegistry.register({ id: editor.id, label: editor.label, extensions: editor.extensions, open: async path => {
        try {
          const result = unwrap(await window.slx.extensionsExecute(id, record.contributes.commands[0]?.command || '', { path }));
          log(`${editor.label}: ${typeof result === 'string' ? result : JSON.stringify(result)}`);
        } catch (error) {
          await deactivateExtension(id).catch(() => {});
          throw error;
        }
      } }));
    },
  });
  try {
    await contributions.activate(contributionId);
    activeExtensions.set(id, { record: { ...record, state: 'active' }, remove });
    renderExtensionViews();
    log(`Extension activated: ${id}`);
  } catch (error) { remove(); await window.slx.extensionsDeactivate(id); throw error; }
}
async function deactivateExtension(id: string): Promise<void> {
  const active = activeExtensions.get(id); if (!active) return;
  contributions.deactivate(`extension.${id}`); active.remove(); activeExtensions.delete(id); renderExtensionViews();
  await window.slx.extensionsDeactivate(id); log(`Extension deactivated: ${id}`);
}
function inspectedModel(path: string, data: ModelViewport): void {
  const unsupported = Array.isArray(data.metadata.unsupported_features) ? data.metadata.unsupported_features.filter((feature): feature is string => typeof feature === 'string') : [];
  modelProblems.set(path, unsupported.map(feature => ({ path, message: `Static inspection does not model ${feature}.`, severity: 'warning', source: 'SLX parser' })));
  problemsService.replace([...modelProblems.values()].flat());
  log(`${path}: static model view — ${data.system_blocks} blocks, ${data.system_lines} connections; MATLAB not started.`);
}
function selectPanel(panel: 'output' | 'problems'): void {
  element('output-view').hidden = panel !== 'output';
  element('problems-view').hidden = panel !== 'problems';
  element('output-tab').classList.toggle('selected', panel === 'output');
  element('problems-tab').classList.toggle('selected', panel === 'problems');
}
function renderProblems(): void {
  const problems = problemsService.snapshot();
  element('problem-count').textContent = problems.length ? `(${problems.length})` : '';
  element('problems').replaceChildren(...problems.map(problem => {
    const row = document.createElement('button');
    row.className = 'problem-row'; row.role = 'listitem';
    row.append(
      Object.assign(document.createElement('span'), { className: 'problem-severity', textContent: problem.severity.toUpperCase() }),
      document.createTextNode(`${problem.path}${problem.line ? `:${problem.line}` : ''} — ${problem.message}`),
      Object.assign(document.createElement('span'), { className: 'problem-source', textContent: problem.source || 'diagnostics' }),
    );
    row.onclick = () => { selectPanel('output'); const editor = editorRegistry.resolve(problem.path); if (editor) void Promise.resolve(editor.open(problem.path)).catch(report); else log(`${problem.path}: no registered editor for this diagnostic.`); };
    return row;
  }));
}
problemsService.subscribe(renderProblems);
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
const modelEditors = new ModelEditors(element('model-stage'), files, renderEditors, inspectedModel);
const settings = new SettingsController(element<HTMLDialogElement>('settings'), files, state => {
  configuration.load('user', state.user.values);
  configuration.load('workspace', state.workspace.values);
  editors.configure({ fontSize: configuration.get<number>('editor.fontSize'), minimap: configuration.get<boolean>('editor.minimap') });
}, () => !!workspace, log);
const contributions = new WorkbenchContributionRegistry();
contributions.register({
  id: 'builtin.core',
  activate(context) {
    context.add(views.register({ id: 'workbench.explorer', title: 'Explorer', location: 'sidebar' }));
    context.add(views.register({ id: 'workbench.output', title: 'Output', location: 'panel' }));
    context.add(editorRegistry.register({ id: 'editor.matlabText', label: 'MATLAB text', extensions: ['.m'], open: async path => { activeKind = 'text'; renderEditors(); await editors.open(path); } }));
    context.add(editorRegistry.register({ id: 'editor.simulinkViewport', label: 'Simulink static viewport', extensions: ['.slx'], open: async path => { activeKind = 'model'; renderEditors(); await modelEditors.open(path); } }));
  },
});
const builtInActivation = contributions.activate('builtin.core').catch(error => { report(error); throw error; });
let lastTabSignature = '';
function renderEditors(): void {
  const signature = `${activeKind}\n${[...editors.documents.values()].map(document => `${document.path}|${editors.dirty(document)}|${editors.active === document}`).join('\n')}\n${[...modelEditors.documents.values()].map(document => `${document.path}|${modelEditors.active === document}`).join('\n')}`;
  if (signature !== lastTabSignature || !element('tabs').childElementCount) {
    lastTabSignature = signature;
    element('welcome').hidden = editors.documents.size > 0 || modelEditors.documents.size > 0;
    element('monaco').hidden = activeKind !== 'text' || !editors.active;
    element('model-stage').hidden = activeKind !== 'model' || !modelEditors.active;
    element('tabs').replaceChildren(...[
    ...[...editors.documents.values()].map(opened => {
      const wrapper = document.createElement('div');
      wrapper.className = `tab-wrap${activeKind === 'text' && editors.active === opened ? ' active' : ''}`;
      const tab = document.createElement('button');
      tab.className = 'tab-select'; tab.role = 'tab';
      tab.setAttribute('aria-selected', String(activeKind === 'text' && editors.active === opened));
      tab.setAttribute('aria-label', opened.path); tab.textContent = `${opened.path.split('/').pop()}${editors.dirty(opened) ? ' ●' : ''}`;
      tab.onclick = () => { activeKind = 'text'; editors.select(opened.path); };
      const close = document.createElement('button'); close.className = 'tab-close'; close.textContent = '×';
      close.setAttribute('aria-label', `Close ${opened.path}`);
      close.onclick = () => void closeEditor('text', opened.path).catch(report);
      wrapper.append(tab, close); return wrapper;
    }),
    ...[...modelEditors.documents.values()].map(opened => {
      const wrapper = document.createElement('div'); wrapper.className = `tab-wrap model-tab${activeKind === 'model' && modelEditors.active === opened ? ' active' : ''}`;
      const tab = document.createElement('button'); tab.className = 'tab-select'; tab.role = 'tab';
      tab.setAttribute('aria-selected', String(activeKind === 'model' && modelEditors.active === opened)); tab.setAttribute('aria-label', opened.path);
      tab.textContent = `▦ ${opened.path.split('/').pop()}`; tab.onclick = () => { activeKind = 'model'; modelEditors.select(opened.path); };
      const close = document.createElement('button'); close.className = 'tab-close'; close.textContent = '×'; close.setAttribute('aria-label', `Close ${opened.path}`);
      close.onclick = () => { closeEditor('model', opened.path).catch(report); }; wrapper.append(tab, close); return wrapper;
    }),
    ]);
  } else {
    element('welcome').hidden = editors.documents.size > 0 || modelEditors.documents.size > 0;
    element('monaco').hidden = activeKind !== 'text' || !editors.active;
    element('model-stage').hidden = activeKind !== 'model' || !modelEditors.active;
  }
  const activePath = activeKind === 'model' ? modelEditors.active?.path : editors.active?.path;
  element('breadcrumbs').textContent = activePath?.replaceAll('/', '  ›  ') || 'Workspace';
  element('document-status').textContent = activeKind === 'model' ? 'Static model · read-only' : editors.position();
}
async function closeEditor(kind: 'text' | 'model', path: string): Promise<void> {
  if (kind === 'model') {
    const wasActive = activeKind === 'model' && modelEditors.active?.path === path;
    modelEditors.close(path); modelProblems.delete(path); problemsService.replace([...modelProblems.values()].flat());
    if (wasActive && !modelEditors.active && editors.active) activeKind = 'text';
  } else {
    const wasActive = activeKind === 'text' && editors.active?.path === path;
    if (!await editors.close(path)) return;
    if (wasActive && !editors.active && modelEditors.active) activeKind = 'model';
  }
  renderEditors();
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
  await builtInActivation;
  workspace = info;
  element('workspace-name').textContent = info.root.split(/[\\/]/).pop()?.toUpperCase() || info.root;
  element('workspace-name').title = info.root;
  element('workspace-status').textContent = info.root;
  await settings.reload();
  await refreshMatlabStatus();
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
  if (selected) { modelEditors.closeAll(); modelProblems.clear(); problemsService.clear(); await setWorkspace(selected); }
} });
commands.register({ id: 'workspace.refresh', title: 'Workspace: Refresh Explorer', enabled: () => !!workspace, run: refresh });
commands.register({ id: 'file.save', title: 'File: Save', enabled: () => activeKind === 'text' && !!editors.active, run: () => editors.save() });
commands.register({ id: 'file.reload', title: 'File: Reload from Disk', enabled: () => activeKind === 'text' && !!editors.active, run: () => editors.reload() });
commands.register({ id: 'settings.show', title: 'Settings: Show Effective Configuration', run: async () => { await settings.reload(); log(JSON.stringify(configuration.effective(), null, 2)); } });
commands.register({ id: 'settings.edit', title: 'Settings: Edit Configuration', run: () => settings.show() });
commands.register({ id: 'matlab.status', title: 'MATLAB: Show Runtime Status', enabled: () => !!workspace, run: async () => {
  const status = await refreshMatlabStatus();
  if (status) log(`${status.detail}. Session: ${status.state}${status.session_id ? ` (${status.session_id.slice(0, 8)})` : ''}.`);
} });
commands.register({ id: 'matlab.command', title: 'MATLAB: Run Command Window Input…', enabled: () => !!workspace && !matlabJob, run: async () => {
  const command = await requestMatlabCommand();
  if (command) await startMatlabCommand(command);
} });
commands.register({ id: 'matlab.runActive', title: 'MATLAB: Run Active Script', enabled: () => !!workspace && !matlabJob && activeKind === 'text' && !!editors.active?.path.endsWith('.m'), run: async () => {
  if (editors.active) await startMatlabRun(editors.active.path);
} });
commands.register({ id: 'model.applyEdit', title: 'Simulink: Apply Validated Model Edit…', enabled: () => !!workspace && !matlabJob && activeKind === 'model' && !!modelEditors.active, run: async () => {
  const active = modelEditors.active;
  if (!active) return;
  const edit = await requestModelEdit();
  if (!edit) return;
  const result = unwrap(await window.slx.applyModelEdit(active.path, edit));
  log(`Simulink model edit applied: ${result.message || 'saved in place'} (MATLAB/Simulink).`);
  await modelEditors.reload(active.path);
} });
commands.register({ id: 'matlab.stop', title: 'MATLAB: Stop Active Job', enabled: () => !!matlabJob, run: async () => {
  const current = matlabJob;
  if (!current) return;
  const result = current.kind === 'command' ? await window.slx.matlabStopCommand(current.id) : await window.slx.matlabStopRun(current.id);
  log(`MATLAB ${current.kind} stop requested (${unwrap(result).state}).`);
} });
commands.register({ id: 'extensions.list', title: 'Extensions: List Trusted Extensions', run: async () => {
  const records = await listExtensions();
  log(records.length ? records.map(record => `${record.id} · ${record.state}${record.error ? ` · ${record.error}` : ''}`).join('\n') : 'No trusted extensions discovered.');
} });
commands.register({ id: 'extensions.activate', title: 'Extensions: Activate Trusted Extension…', run: async () => {
  const records = await listExtensions();
  const candidate = records.find(record => record.state === 'inactive');
  if (!candidate) { log('No inactive trusted extension is available.'); return; }
  await activateExtension(candidate.id);
} });
commands.register({ id: 'extensions.deactivate', title: 'Extensions: Deactivate Active Extension', enabled: () => activeExtensions.size > 0, run: async () => {
  const id = activeExtensions.keys().next().value as string | undefined;
  if (id) await deactivateExtension(id);
} });
commands.register({ id: 'workbench.reloadContributions', title: 'Workbench: Reload Built-in Contributions', run: async () => {
  await builtInActivation;
  contributions.deactivate('builtin.core');
  await contributions.activate('builtin.core');
  log('Workbench contributions reloaded; registrations were disposed and recreated.');
} });
commands.register({ id: 'backend.restart', title: 'Backend: Restart Python Service', enabled: () => !!workspace, run: async () => {
  const info = await files.restartBackend();
  workspace = info;
  await settings.reload();
  await refresh();
  log('Python backend restarted; pending requests were not replayed.');
} });
commands.register({ id: 'file.close', title: 'File: Close Editor', enabled: () => (activeKind === 'text' ? !!editors.active : !!modelEditors.active), run: () => activeKind === 'text' ? editors.active && closeEditor('text', editors.active.path) : modelEditors.active && closeEditor('model', modelEditors.active.path) });
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
  if (id && !document.querySelector('dialog[open]')) { event.preventDefault(); event.stopPropagation(); void commands.execute(id).catch(report); }
}, true);
element('clear-output').onclick = () => { outputService.clear(); output.textContent = ''; };
element('output-tab').onclick = () => selectPanel('output');
element('problems-tab').onclick = () => selectPanel('problems');
void files.workspace().then(async info => {
  if (info) await setWorkspace(info);
  else await settings.reload();
  document.body.dataset.ready = 'true';
}).catch(report);

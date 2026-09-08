import './style.css';
import { CommandRegistry } from '../../../packages/commands';
import { ConfigurationStore, DESKTOP_SCHEMAS } from '../../../packages/configuration';
import { DesktopServices } from '../../../packages/core/services';
import { DocumentEditors } from '../../../packages/editor/documents';
import { CustomEditorRegistry } from '../../../packages/editor/registry';
import { ModelEditors } from '../../../packages/model/view';
import type { ModelAction, ModelView } from '../../../packages/model/view';
import { showModelJob } from '../../../packages/model/results';
import { MatlabResultsPanel } from '../../../packages/matlab/results';
import { OutputService, ProblemsService, ViewRegistry, WorkbenchContributionRegistry } from '../../../packages/workbench';
import type { Problem } from '../../../packages/workbench';
import { unwrap } from '../../../packages/protocol';
import type { ExtensionRecord, MatlabJobStatus, MatlabRuntimeStatus, ModelJobStatus, ModelViewport, WorkspaceInfo } from '../../../packages/protocol';
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
let activeKind: 'text' | 'model' | 'custom' = 'text';
const customEditors = new Map<string, { label: string; editorId: string; element: HTMLElement }>();
const customStage = document.createElement('div'); customStage.id = 'custom-stage'; customStage.hidden = true;
document.getElementById('editor-stage')!.append(customStage);
const modelProblems = new Map<string, Problem[]>();
let closing = false;
let explorerGeneration = 0;
let matlabJob: { kind: 'command' | 'run'; id: string; stdoutOffset: number; stderrOffset: number } | null = null;
let matlabEpoch = 0;
let startingMatlab = false;
let modelJob: ModelJobStatus | null = null;
let startingModel = false;
const modelResults = document.createElement('div'); modelResults.id = 'model-results';
const modelResultView = document.createElement('div'); modelResultView.id = 'model-view'; modelResultView.hidden = true; modelResultView.append(modelResults);
document.querySelector('.panel')!.append(modelResultView);
const modelTab = document.createElement('button'); modelTab.id = 'model-tab'; modelTab.textContent = 'MODEL JOBS';
document.querySelector('.panel-tabs')!.append(modelTab); modelTab.onclick = () => selectPanel('model');
const activeExtensions = new Map<string, { record: ExtensionRecord; remove: () => void }>();
function renderOutput(): void {
  output.textContent = outputService.snapshot().map(entry => entry.text).join('\n').slice(-65_536);
  output.scrollTop = output.scrollHeight;
}
function log(message: string): void { outputService.append(message); renderOutput(); }
function stream(text: string, error = false): void { outputService.appendChunk(text, error ? 'error' : 'info'); renderOutput(); }
function report(error: unknown): void { log((error as Error).message || String(error)); }
function renderMatlabStatus(status: MatlabRuntimeStatus): void {
  const label = status.state === 'ready' ? 'MATLAB ready · persistent session' : status.available ? 'MATLAB stopped · opt-in' : 'MATLAB unavailable';
  document.querySelector<HTMLElement>('.session-state')!.textContent = matlabJob ? `MATLAB ${matlabJob.kind} running` : label;
  element('document-status').textContent = matlabJob ? `MATLAB ${matlabJob.kind} running` : status.state === 'ready' ? 'MATLAB session ready' : 'Ready';
  matlabResults.setBusy(!!matlabJob || startingMatlab);
}
async function refreshMatlabStatus(): Promise<MatlabRuntimeStatus | null> {
  if (!workspace) return null;
  const status = unwrap(await window.slx.matlabStatus());
  renderMatlabStatus(status);
  return status;
}
function matlabResultSummary(kind: 'command' | 'run', status: MatlabJobStatus): void {
  const result = status.result;
  if (!result) { log(`MATLAB ${kind} ${status.state}: ${status.error || 'No result was returned; the operation was not replayed.'}`); return; }
  matlabResults.show(kind, status.id, result);
  if (result.state_lost || result.session_reset) log('MATLAB session state was lost/reset. Prior commands were not replayed.');
  if (result.error?.message) {
    const problemPath = result.error.file || result.path || result.command || 'MATLAB';
    const problem: Problem = { path: problemPath, message: result.error.message, severity: 'error', line: result.error.line || undefined, source: 'MATLAB' };
    modelProblems.set(`matlab:${kind}`, [problem]);
    problemsService.replace([...modelProblems.values()].flat());
    log(`MATLAB ${kind} failed: ${result.error.message}`);
  } else {
    const variables = result.total_variables ?? result.variables?.length ?? 0;
    const figures = result.total_figures ?? result.figures?.length ?? 0;
    log(`MATLAB ${kind} finished${result.elapsed_seconds ? ` in ${result.elapsed_seconds.toFixed(2)}s` : ''} · ${variables} variables · ${figures} figures${result.state_lost ? ' · session state discarded' : ''}.`);
  }
  if (result.debug_events?.length) log(`MATLAB tracepoints: ${result.debug_events.map(event => `${event.file}:${event.line}`).join(', ')}`);
}
async function pollMatlabJob(current = matlabJob): Promise<void> {
  if (!current || current !== matlabJob) return;
  try {
    const status = current.kind === 'command'
      ? unwrap(await window.slx.matlabCommandStatus(current.id, current.stdoutOffset, current.stderrOffset))
      : unwrap(await window.slx.matlabRunStatus(current.id, current.stdoutOffset, current.stderrOffset));
    if (current !== matlabJob) return;
    current.stdoutOffset = status.stdout_offset;
    current.stderrOffset = status.stderr_offset;
    if (status.stdout_delta) stream(status.stdout_delta);
    if (status.stderr_delta) stream(status.stderr_delta, true);
    if (status.state === 'running' || status.output_pending) { window.setTimeout(() => void pollMatlabJob(current), 90); return; }
    matlabJob = null;
    matlabResultSummary(current.kind, status);
    await refreshMatlabStatus();
  } catch (error) { if (current === matlabJob) { matlabJob = null; matlabResults.setBusy(false); report(error); } }
}
async function beginMatlabJob(kind: 'command' | 'run', start: () => Promise<MatlabJobStatus>, label: string): Promise<void> {
  if (matlabJob || startingMatlab || modelJob || startingModel) throw new Error('A MATLAB or model job is already active');
  const epoch = matlabEpoch; startingMatlab = true; matlabResults.setBusy(true);
  try {
    const status = await start();
    if (epoch !== matlabEpoch) return;
    modelProblems.delete(`matlab:${kind}`); problemsService.replace([...modelProblems.values()].flat());
    // The start response may already contain output from a fast command. Poll
    // from zero so that first chunk is never skipped.
    matlabJob = { kind, id: status.id, stdoutOffset: 0, stderrOffset: 0 };
    log(`MATLAB ${kind} started: ${label}`);
    await refreshMatlabStatus();
    void pollMatlabJob(matlabJob);
  } finally { if (epoch === matlabEpoch) { startingMatlab = false; matlabResults.setBusy(!!matlabJob); } }
}
async function startMatlabCommand(command: string): Promise<void> {
  await beginMatlabJob('command', async () => unwrap(await window.slx.matlabStartCommand(command)), command);
}
async function startMatlabRun(path: string, options?: { code?: string; startLine?: number }): Promise<void> {
  await beginMatlabJob('run', async () => unwrap(await window.slx.matlabStartRun(path, options)), `${path}${options?.startLine ? `:${options.startLine} (current buffer section)` : ' (saved file)'}`);
}
function requestMatlabCommand(options: { title?: string; label?: string; value?: string; action?: string; help?: string } = {}): Promise<string | null> {
  const dialog = element<HTMLDialogElement>('matlab-command');
  const input = element<HTMLTextAreaElement>('matlab-command-input');
  const run = element<HTMLButtonElement>('matlab-command-run');
  const cancel = element<HTMLButtonElement>('matlab-command-cancel');
  const title = element('matlab-command-title');
  const oldTitle = title.textContent; const oldAction = run.textContent;
  const help = dialog.querySelector<HTMLElement>('.dialog-help')!; const oldHelp = help.textContent;
  return new Promise(resolve => {
    const finish = (value: string | null) => { dialog.close(); title.textContent = oldTitle; run.textContent = oldAction; help.textContent = oldHelp; input.setAttribute('aria-label', 'MATLAB command'); run.onclick = null; cancel.onclick = null; dialog.oncancel = null; input.onkeydown = null; resolve(value); };
    run.onclick = () => finish(input.value.trim() || null);
    cancel.onclick = () => finish(null);
    dialog.oncancel = event => { event.preventDefault(); finish(null); };
    input.onkeydown = event => { if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); finish(input.value.trim() || null); } };
    title.textContent = options.title || 'MATLAB Command Window'; run.textContent = options.action || 'Run command'; input.setAttribute('aria-label', options.label || 'MATLAB command');
    if (options.help) help.textContent = options.help;
    input.value = options.value || ''; dialog.showModal(); input.focus(); input.select();
  });
}
function requestModelEdit(initial: Readonly<Record<string, unknown>>): Promise<Readonly<Record<string, unknown>> | null> {
  const dialog = element<HTMLDialogElement>('matlab-command');
  const title = element('matlab-command-title');
  const help = dialog.querySelector<HTMLElement>('.dialog-help')!;
  const input = element<HTMLTextAreaElement>('matlab-command-input');
  const run = element<HTMLButtonElement>('matlab-command-run');
  const cancel = element<HTMLButtonElement>('matlab-command-cancel');
  const previousTitle = title.textContent || '';
  const previousHelp = help.textContent || '';
  const previousAction = run.textContent;
  return new Promise(resolve => {
    const finish = (value: Readonly<Record<string, unknown>> | null) => { dialog.close(); title.textContent = previousTitle; help.textContent = previousHelp; run.textContent = previousAction; input.setAttribute('aria-label', 'MATLAB command'); run.onclick = null; cancel.onclick = null; dialog.oncancel = null; input.onkeydown = null; resolve(value); };
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
    help.textContent = 'Explicitly runs MATLAB/Simulink (including model callbacks) on an isolated copy. Save replaces the original only if its SHA-256 still matches. Command Window variables are not shared.';
    run.textContent = 'Apply and Save'; input.setAttribute('aria-label', 'Model edit JSON');
    input.value = JSON.stringify(initial, null, 2); dialog.showModal(); input.focus(); input.select();
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
async function activateExtension(id: string, restart = false): Promise<void> {
  if (activeExtensions.has(id)) return;
  const record = unwrap(await (restart ? window.slx.extensionsRestart(id) : window.slx.extensionsActivate(id)));
  const contributionId = `extension.${id}`;
  const remove = contributions.register({
    id: contributionId,
    activate(context) {
      for (const command of record.contributes.commands) {
        context.add(commands.register({ id: command.command, title: command.title, run: async () => {
          try {
            const result = unwrap(await window.slx.extensionsExecute(id, command.command, {}));
            log(`${command.title}: ${typeof result === 'string' ? result : JSON.stringify(result)}`);
            if (id === 'firstparty.matlab' && command.command === 'firstparty.matlab.command') {
              const code = await requestMatlabCommand(); if (code) await startMatlabCommand(code);
            } else if (id === 'firstparty.matlab' && command.command === 'firstparty.matlab.variables') selectPanel('matlab');
            else if (id === 'firstparty.simulink' && modelEditors.active) {
              await modelAction(command.command.endsWith('.simulate') ? 'simulate' : 'edit', modelEditors.active);
            }
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
          const panel = document.createElement('article'); panel.className = 'custom-editor'; panel.dataset.editorId = editor.id;
          panel.append(Object.assign(document.createElement('h2'), { textContent: editor.label }), Object.assign(document.createElement('p'), { textContent: `${path} · trusted extension contribution` }), Object.assign(document.createElement('pre'), { textContent: typeof result === 'string' ? result : JSON.stringify(result, null, 2) }));
          customEditors.get(path)?.element.remove(); customEditors.set(path, { label: editor.label, editorId: editor.id, element: panel });
          customStage.replaceChildren(...[...customEditors.values()].map(item => item.element)); activeKind = 'custom'; renderEditors();
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
  contributions.deactivate(`extension.${id}`); active.remove();
  for (const [path, editor] of customEditors) if (editor.editorId.startsWith(`${id}.`)) { editor.element.remove(); customEditors.delete(path); }
  activeExtensions.delete(id); renderEditors(); renderExtensionViews();
  await window.slx.extensionsDeactivate(id); log(`Extension deactivated: ${id}`);
}
function inspectedModel(path: string, data: ModelViewport): void {
  const unsupported = Array.isArray(data.metadata.unsupported_features) ? data.metadata.unsupported_features.filter((feature): feature is string => typeof feature === 'string') : [];
  modelProblems.set(path, unsupported.map(feature => ({ path, message: `Static inspection does not model ${feature}.`, severity: 'warning', source: 'SLX parser' })));
  problemsService.replace([...modelProblems.values()].flat());
  log(`${path}: static model view — ${data.system_blocks} blocks, ${data.system_lines} connections; MATLAB not started.`);
}
function selectPanel(panel: 'output' | 'problems' | 'matlab' | 'model'): void {
  for (const name of ['output', 'problems', 'matlab', 'model']) {
    element(`${name}-view`).hidden = panel !== name;
    element(`${name}-tab`).classList.toggle('selected', panel === name);
  }
  element('workbench').classList.toggle('results-expanded', panel === 'matlab' || panel === 'model');
}
async function navigateProblem(path: string, line = 1, column = 1): Promise<void> {
  const normalized = path.replaceAll('\\', '/'); const root = workspace?.root.replaceAll('\\', '/').replace(/\/$/, '');
  const relative = root && normalized.toLowerCase().startsWith(`${root.toLowerCase()}/`) ? normalized.slice(root.length + 1) : normalized;
  if (/^(?:[a-z]:|\/)/i.test(relative)) { log(`${path}: diagnostic is outside this workspace.`); return; }
  const editor = editorRegistry.resolve(relative);
  if (!editor) { log(`${relative}: no registered editor for this diagnostic.`); return; }
  await editor.open(relative);
  if (relative.toLowerCase().endsWith('.m')) editors.reveal(relative, line, column);
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
    row.onclick = () => void navigateProblem(problem.path, problem.line || 1, problem.column || 1).catch(report);
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
const matlabResults = new MatlabResultsPanel(element('matlab-results'), window.slx, async (name, preview) => {
  const expression = await requestMatlabCommand({ title: `Edit MATLAB variable: ${name}`, label: 'Variable expression', value: preview, action: 'Apply variable' });
  if (expression !== null) await beginMatlabJob('command', async () => unwrap(await window.slx.matlabSetVariable(name, expression)), `set variable ${name}`);
}, navigateProblem, report);
function resetMatlabView(): void { ++matlabEpoch; matlabJob = null; startingMatlab = false; matlabResults.clear(); modelJob = null; startingModel = false; modelResults.replaceChildren(); }
const modelEditors = new ModelEditors(element('model-stage'), files, renderEditors, inspectedModel, (action, view, parameter) => { void modelAction(action, view, parameter).catch(report); });
function modelBusy(): boolean { return !!matlabJob || startingMatlab || !!modelJob || startingModel; }
async function startModelJob(start: () => Promise<ModelJobStatus>): Promise<void> {
  if (modelBusy()) throw new Error('Wait for or stop the active MATLAB/model job first');
  startingModel = true; const epoch = matlabEpoch;
  try {
    const job = await start();
    if (epoch !== matlabEpoch) return;
    modelJob = job; showModelJob(modelResults, job); selectPanel('model');
    log(`Simulink ${job.kind} started: ${job.path} · independent MATLAB batch session.`);
    void pollModelJob(job);
  } finally { if (epoch === matlabEpoch) startingModel = false; }
}
async function pollModelJob(current: ModelJobStatus): Promise<void> {
  if (current !== modelJob) return;
  try {
    const status = unwrap(await window.slx.modelJobStatus(current.id));
    if (current !== modelJob) return;
    if (status.state === 'running') { window.setTimeout(() => void pollModelJob(current), 150); return; }
    modelJob = null; showModelJob(modelResults, status);
    log(`Simulink ${status.kind} ${status.state}: ${status.error || status.result?.message || status.path}`);
    if (status.saved_sha256) await modelEditors.reload(status.path);
    if (status.error) {
      modelProblems.set(`model:${status.path}`, [{ path: status.path, message: status.error, severity: 'error', source: 'Simulink batch' }]);
      problemsService.replace([...modelProblems.values()].flat());
    }
  } catch (error) { if (current === modelJob) { modelJob = null; report(error); } }
}
async function modelAction(action: ModelAction, view: ModelView, parameter?: string): Promise<void> {
  if (modelBusy()) throw new Error('Wait for or stop the active MATLAB/model job first');
  const data = view.snapshot(); if (!data) throw new Error('Reload the model before editing or simulating');
  if (action === 'undo' || action === 'redo') {
    const history = unwrap(await window.slx.modelHistory(view.path, action));
    await view.reload(); log(`Model ${action}: ${history.undo_count} undo / ${history.redo_count} redo · ${history.sha256}`); return;
  }
  if (action === 'simulate') {
    const stopTime = await requestMatlabCommand({ title: 'Simulate model', label: 'Simulation stop time', value: '10', action: 'Run simulation', help: 'Independent MATLAB batch session. Model callbacks execute. Command Window variables are NOT shared. The original SLX is not modified; configure workspace variables inside the model/project.' });
    if (stopTime !== null) await startModelJob(async () => unwrap(await window.slx.startSimulation(view.path, data.sha256, stopTime)));
    return;
  }
  let operations: Readonly<Record<string, unknown>>[] = [{ op: 'add_block', block_type: 'gain', name: 'NewGain', parent: '', position: [100, 100, 160, 140], parameters: { Gain: '1' } }];
  const block = view.selectedBlock();
  if (action === 'parameter' && block && parameter) {
    const after = await requestMatlabCommand({ title: `${block.path} · ${parameter}`, label: 'Model parameter value', value: block.parameters[parameter], action: 'Apply and Save', help: 'Explicit MATLAB/Simulink edit. Callbacks may execute. The original model is saved only after validation and an external-change check; Undo is available this session.' });
    if (after === null) return;
    operations = [{ op: 'set_param', block_path: block.path, sid: block.sid, parameter, before: block.parameters[parameter], after }];
  }
  const initial = { schema_version: '0.1', model_name: data.name, source_sha256: data.sha256, operations };
  const edit = action === 'parameter' ? initial : await requestModelEdit(initial);
  if (edit) await startModelJob(async () => unwrap(await window.slx.startModelEdit(view.path, edit)));
}
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
    element('welcome').hidden = editors.documents.size > 0 || modelEditors.documents.size > 0 || customEditors.size > 0;
    element('monaco').hidden = activeKind !== 'text' || !editors.active;
    element('model-stage').hidden = activeKind !== 'model' || !modelEditors.active;
    customStage.hidden = activeKind !== 'custom' || !customEditors.size;
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
    ...[...customEditors.entries()].map(([path, opened]) => {
      const wrapper = document.createElement('div'); wrapper.className = `tab-wrap custom-tab${activeKind === 'custom' && customEditors.get(path) === opened ? ' active' : ''}`;
      const tab = document.createElement('button'); tab.className = 'tab-select'; tab.role = 'tab'; tab.setAttribute('aria-selected', String(activeKind === 'custom' && customEditors.get(path) === opened)); tab.setAttribute('aria-label', path); tab.textContent = `◇ ${path.split('/').pop()}`; tab.onclick = () => { activeKind = 'custom'; customStage.replaceChildren(...[...customEditors.values()].map(item => item.element)); renderEditors(); };
      const close = document.createElement('button'); close.className = 'tab-close'; close.textContent = '×'; close.setAttribute('aria-label', `Close ${path}`); close.onclick = () => void closeEditor('custom', path); wrapper.append(tab, close); return wrapper;
    }),
    ]);
  } else {
    element('welcome').hidden = editors.documents.size > 0 || modelEditors.documents.size > 0 || customEditors.size > 0;
    element('monaco').hidden = activeKind !== 'text' || !editors.active;
    element('model-stage').hidden = activeKind !== 'model' || !modelEditors.active;
    customStage.hidden = activeKind !== 'custom' || !customEditors.size;
  }
  const activePath = activeKind === 'model' ? modelEditors.active?.path : activeKind === 'custom' ? [...customEditors.keys()][0] : editors.active?.path;
  element('breadcrumbs').textContent = activePath?.replaceAll('/', '  ›  ') || 'Workspace';
  element('document-status').textContent = activeKind === 'model' ? 'Static model · read-only' : activeKind === 'custom' ? 'Custom editor · trusted extension' : editors.position();
}
async function closeEditor(kind: 'text' | 'model' | 'custom', path: string): Promise<void> {
  if (kind === 'model') {
    const wasActive = activeKind === 'model' && modelEditors.active?.path === path;
    modelEditors.close(path); modelProblems.delete(path); problemsService.replace([...modelProblems.values()].flat());
    if (wasActive && !modelEditors.active && editors.active) activeKind = 'text';
  } else if (kind === 'text') {
    const wasActive = activeKind === 'text' && editors.active?.path === path;
    if (!await editors.close(path)) return;
    if (wasActive && !editors.active && modelEditors.active) activeKind = 'model';
  } else { customEditors.get(path)?.element.remove(); customEditors.delete(path); if (!customEditors.size) activeKind = modelEditors.active ? 'model' : 'text'; }
  renderEditors();
}
async function directory(parent: HTMLElement, relative: string, cursor: number, generation: number): Promise<void> {
  const page = await files.list(relative, cursor);
  if (generation !== explorerGeneration) return;
  for (const item of page.items) {
    const row = document.createElement('button');
    row.className = `tree-row ${item.kind === 'directory' ? 'directory' : ''}`;
    row.role = 'treeitem'; row.setAttribute('aria-label', item.path);
    const icon = document.createElement('span'); icon.textContent = item.kind === 'directory' ? '›' : item.kind === 'm' ? 'M' : item.kind === 'slxpreview' ? '◇' : '▦'; icon.setAttribute('aria-hidden', 'true');
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
  resetMatlabView();
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
  const active = editors.active; if (!active) return;
  if (editors.dirty(active)) {
    if (await decide('Save before running', `${active.path} contains unsaved changes.`, ['Cancel', 'Save and Run']) !== 'Save and Run') return;
    await editors.save(active);
  }
  await startMatlabRun(active.path);
} });
commands.register({ id: 'matlab.runSection', title: 'MATLAB: Run Current Section', enabled: () => !!workspace && !matlabJob && !startingMatlab && activeKind === 'text' && !!editors.active, run: async () => {
  const section = editors.section();
  await startMatlabRun(section.path, { code: section.code, startLine: section.startLine });
} });
commands.register({ id: 'matlab.results', title: 'MATLAB: Show Variables and Figures', run: () => selectPanel('matlab') });
commands.register({ id: 'model.applyEdit', title: 'Simulink: Apply Validated Model Edit…', enabled: () => !!workspace && !matlabJob && activeKind === 'model' && !!modelEditors.active, run: async () => {
  const active = modelEditors.active;
  if (!active) return;
  await modelAction('edit', active);
} });
for (const [action, title] of [['undo', 'Simulink: Undo Model Edit'], ['redo', 'Simulink: Redo Model Edit'], ['simulate', 'Simulink: Simulate Active Model…']] as const) commands.register({ id: `model.${action}`, title, enabled: () => !modelBusy() && activeKind === 'model' && !!modelEditors.active, run: () => modelAction(action, modelEditors.active!) });
commands.register({ id: 'model.stop', title: 'Simulink: Stop Active Model Job', enabled: () => !!modelJob, run: async () => { if (modelJob) unwrap(await window.slx.stopModelJob(modelJob.id)); } });
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
commands.register({ id: 'extensions.restart', title: 'Extensions: Restart Failed Extension…', run: async () => {
  const records = (await listExtensions()).filter(record => record.state === 'failed');
  if (!records.length) { log('No failed extension needs restarting.'); return; }
  const id = records.length === 1 ? records[0].id : await decide('Restart trusted extension', 'Restarting executes its trusted local entry point again. Previous commands are never replayed.', ['Cancel', ...records.map(record => record.id)]);
  if (id !== 'Cancel') await activateExtension(id, true);
} });
commands.register({ id: 'workbench.reloadContributions', title: 'Workbench: Reload Built-in Contributions', run: async () => {
  await builtInActivation;
  contributions.deactivate('builtin.core');
  await contributions.activate('builtin.core');
  log('Workbench contributions reloaded; registrations were disposed and recreated.');
} });
commands.register({ id: 'backend.restart', title: 'Backend: Restart Python Service', enabled: () => !!workspace, run: async () => {
  const info = await files.restartBackend();
  resetMatlabView();
  workspace = info;
  await settings.reload();
  await refresh();
  log('Python backend restarted; pending requests were not replayed.');
} });
commands.register({ id: 'file.close', title: 'File: Close Editor', enabled: () => activeKind === 'text' ? !!editors.active : activeKind === 'model' ? !!modelEditors.active : !!customEditors.size, run: () => activeKind === 'text' ? editors.active && closeEditor('text', editors.active.path) : activeKind === 'model' ? modelEditors.active && closeEditor('model', modelEditors.active.path) : customEditors.size && closeEditor('custom', [...customEditors.keys()][0]) });
commands.register({ id: 'workbench.palette', title: 'Workbench: Command Palette', run: () => {
  element<HTMLInputElement>('command-search').value = ''; commandResults(); palette.showModal(); element('command-search').focus();
} });
element('command-search').addEventListener('input', commandResults);
element('command-search').addEventListener('keydown', event => { if (event.key === 'Enter') element('command-results').querySelector<HTMLButtonElement>('button:not(:disabled)')?.click(); });
document.querySelectorAll<HTMLButtonElement>('[data-command]').forEach(button => button.onclick = () => void commands.execute(button.dataset.command!).catch(report));
window.slx.onCommand(id => void commands.execute(id).catch(report));
window.slx.onExtensionState(state => {
  if (state.state === 'inactive' && activeExtensions.has(state.id)) { void deactivateExtension(state.id).catch(report); return; }
  if (state.state !== 'failed') return;
  log(`Extension failed: ${state.id} · ${state.error || 'host stopped'}. Use Restart Failed Extension to retry explicitly.`);
  if (activeExtensions.has(state.id)) void deactivateExtension(state.id).catch(report);
});
window.slx.onClose(() => {
  if (closing) return;
  closing = true;
  void (async () => {
    if ((modelBusy() || element('matlab-results').dataset.sessionId) &&
      await decide('Close MATLAB session?', 'Closing stops this app’s owned MATLAB jobs and discards live variables and figures. Commands will not be replayed.', ['Cancel', 'Close session and window']) !== 'Close session and window') return;
    if (await editors.closeAll()) window.slx.confirmClose();
  })().catch(report).finally(() => { closing = false; });
});
window.addEventListener('keydown', event => {
  if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
  const id = event.key.toLowerCase() === 's' ? 'file.save' : event.key.toLowerCase() === 'w' ? 'file.close' : event.shiftKey && event.key.toLowerCase() === 'p' ? 'workbench.palette' : '';
  if (id && !document.querySelector('dialog[open]')) { event.preventDefault(); event.stopPropagation(); void commands.execute(id).catch(report); }
}, true);
element('clear-output').onclick = () => { outputService.clear(); output.textContent = ''; };
element('output-tab').onclick = () => selectPanel('output');
element('problems-tab').onclick = () => selectPanel('problems');
element('matlab-tab').onclick = () => selectPanel('matlab');
void files.workspace().then(async info => {
  if (info) await setWorkspace(info);
  else await settings.reload();
  document.body.dataset.ready = 'true';
}).catch(report);

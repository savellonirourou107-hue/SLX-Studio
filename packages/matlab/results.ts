import type { DesktopAPI, MatlabResult } from '../protocol';
import { unwrap } from '../protocol';

const node = <K extends keyof HTMLElementTagNameMap>(tag: K, text = '') => Object.assign(document.createElement(tag), { textContent: text });

/** A bounded, data-only MATLAB result view. No serialized content is executed. */
export class MatlabResultsPanel {
  private job: { kind: 'command' | 'run'; id: string } | null = null;
  private result: MatlabResult | null = null;
  private revision = 0;
  private busy = false;
  constructor(private readonly element: HTMLElement, private readonly api: DesktopAPI,
    private readonly edit: (name: string, preview: string) => Promise<void>, private readonly navigate: (path: string, line: number) => Promise<void>,
    private readonly report: (error: unknown) => void) { this.clear(); }
  clear(): void {
    ++this.revision; this.job = null; this.result = null;
    delete this.element.dataset.sessionId; delete this.element.dataset.jobId;
    this.element.replaceChildren(node('p', 'Run an explicit MATLAB command or script to inspect variables and figures.'));
  }
  setBusy(value: boolean): void {
    this.busy = value;
    for (const button of this.element.querySelectorAll<HTMLButtonElement>('[data-variable]')) button.disabled = value;
  }
  show(kind: 'command' | 'run', id: string, result: MatlabResult): void {
    ++this.revision; this.job = { kind, id }; this.result = result; this.render();
  }
  private async page(options: { variableCursor?: number; figureCursor?: number; eventCursor?: number }): Promise<void> {
    if (!this.job || !this.result) return;
    const revision = ++this.revision;
    try {
      const result = unwrap(await this.api.matlabResultPage(this.job.kind, this.job.id, {
        variableCursor: this.result.variables_cursor || 0, figureCursor: this.result.figures_cursor || 0,
        eventCursor: this.result.debug_events_cursor || 0, ...options,
      }));
      if (revision !== this.revision) return;
      this.result = result; this.render();
    } catch (error) { if (revision === this.revision) this.report(error); }
  }
  private render(): void {
    const result = this.result; if (!result || !this.job) return;
    this.element.dataset.sessionId = result.session_id || '';
    this.element.dataset.jobId = this.job.id;
    const status = node('p', `${this.job.kind} ${this.job.id} · session ${result.session_id || 'unavailable'}${result.state_lost ? ' · STATE LOST' : ''}`);
    status.className = 'matlab-result-status';
    const columns = node('div'); columns.className = 'matlab-results-columns';
    const variables = node('section'); variables.setAttribute('aria-label', 'MATLAB variables');
    const count = result.total_variables ?? result.variables?.length ?? 0;
    variables.append(node('h3', `Workspace variables (${count})`));
    const table = node('table');
    const header = node('tr'); for (const title of ['Name', 'Class / size', 'Value', '']) header.append(node('th', title)); table.append(header);
    for (const variable of result.variables || []) {
      const row = node('tr'); row.dataset.variableName = variable.name;
      const action = node('td'); const button = node('button', 'Edit');
      button.dataset.variable = variable.name; button.disabled = this.busy; button.setAttribute('aria-label', `Edit variable ${variable.name}`);
      button.onclick = () => void this.edit(variable.name, variable.preview).catch(this.report);
      action.append(button); row.append(node('td', variable.name), node('td', `${variable.class} · ${variable.size}`), node('td', variable.preview), action); table.append(row);
    }
    variables.append(table);
    const previous = node('button', 'Previous variables'); previous.disabled = !(result.variables_cursor || 0);
    previous.onclick = () => void this.page({ variableCursor: Math.max(0, (result.variables_cursor || 0) - 128) });
    const next = node('button', 'Next variables'); next.disabled = result.next_variables_cursor == null;
    next.onclick = () => void this.page({ variableCursor: result.next_variables_cursor! });
    variables.append(previous, next);
    const figures = node('section'); figures.setAttribute('aria-label', 'MATLAB figures');
    figures.append(node('h3', `Exported figures (${result.total_figures ?? result.figures?.length ?? 0})`));
    for (const figure of result.figures || []) {
      if (figure.mime !== 'image/png' || figure.data_base64.length > 4 * 1024 * 1024 || !/^[A-Za-z0-9+/=]+$/.test(figure.data_base64)) continue;
      const image = node('img'); image.alt = figure.name; image.src = `data:image/png;base64,${figure.data_base64}`; figures.append(image);
    }
    if (result.total_figures) {
      const previousFigure = node('button', 'Previous figure'); previousFigure.disabled = !(result.figures_cursor || 0);
      previousFigure.onclick = () => void this.page({ figureCursor: Math.max(0, (result.figures_cursor || 0) - 1) });
      const nextFigure = node('button', 'Next figure'); nextFigure.disabled = result.next_figures_cursor == null;
      nextFigure.onclick = () => void this.page({ figureCursor: result.next_figures_cursor! });
      figures.append(previousFigure, nextFigure);
    }
    const probes = node('details'); probes.append(node('summary', `Non-pausing tracepoints (${result.total_debug_events ?? result.debug_events?.length ?? 0})`));
    for (const event of result.debug_events || []) {
      const button = node('button', `${event.file}:${event.line}`); button.onclick = () => void this.navigate(event.file, event.line).catch(this.report); probes.append(button);
    }
    if (result.next_debug_events_cursor != null) {
      const more = node('button', 'Next tracepoints'); more.onclick = () => void this.page({ eventCursor: result.next_debug_events_cursor! }); probes.append(more);
    }
    figures.append(probes); columns.append(variables, figures); this.element.replaceChildren(status, columns);
  }
}

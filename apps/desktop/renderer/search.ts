import type { DesktopServices } from '../../../packages/core/services';
import type { WorkspaceSearchResponse, WorkspaceSearchResult } from '../../../packages/protocol';

export type WorkspaceSearchOpen = (result: WorkspaceSearchResult) => Promise<void>;

export class WorkspaceSearchController {
  private generation = 0;
  private timer?: ReturnType<typeof setTimeout>;

  constructor(
    private readonly dialog: HTMLDialogElement,
    private readonly input: HTMLInputElement,
    private readonly results: HTMLElement,
    private readonly status: HTMLElement,
    private readonly files: Pick<DesktopServices, 'searchWorkspace'>,
    private readonly openResult: WorkspaceSearchOpen,
    private readonly report: (error: unknown) => void,
  ) {
    this.input.addEventListener('input', () => this.schedule());
    this.input.addEventListener('keydown', event => {
      if (event.key === 'Enter') {
        const first = this.results.querySelector<HTMLButtonElement>('button');
        if (first) { event.preventDefault(); first.click(); }
      } else if (event.key === 'ArrowDown') {
        const first = this.results.querySelector<HTMLButtonElement>('button');
        if (first) { event.preventDefault(); first.focus(); }
      }
    });
    this.results.addEventListener('keydown', event => {
      const target = event.target as HTMLButtonElement;
      if (target.tagName !== 'BUTTON' || (event.key !== 'ArrowDown' && event.key !== 'ArrowUp')) return;
      const buttons = [...this.results.querySelectorAll<HTMLButtonElement>('button')];
      const index = buttons.indexOf(target);
      const next = event.key === 'ArrowDown' ? buttons[index + 1] : buttons[index - 1];
      if (next) { event.preventDefault(); next.focus(); }
      else if (event.key === 'ArrowUp' && index === 0) { event.preventDefault(); this.input.focus(); }
    });
    this.dialog.addEventListener('close', () => this.cancelPending());
  }

  show(): void {
    this.cancelPending();
    this.input.value = '';
    this.results.replaceChildren();
    this.status.textContent = 'Search file names, MATLAB text, and static Simulink blocks/signals. MATLAB is not started.';
    if (!this.dialog.open) this.dialog.showModal();
    this.input.focus();
  }

  private cancelPending(): void {
    ++this.generation;
    clearTimeout(this.timer);
    this.timer = undefined;
  }

  private schedule(delay = 120): void {
    clearTimeout(this.timer);
    const generation = ++this.generation;
    const query = this.input.value.trim();
    if (!query) {
      this.results.replaceChildren();
      this.status.textContent = 'Type a search term. Results are bounded and workspace-scoped.';
      return;
    }
    this.status.textContent = 'Searching…';
    this.timer = setTimeout(() => void this.run(query, generation), delay);
  }

  private async run(query: string, generation: number): Promise<void> {
    try {
      const response = await this.files.searchWorkspace(query, { maxResults: 100, maxFileBytes: 1024 * 1024 });
      if (generation !== this.generation || query !== this.input.value.trim() || !this.dialog.open) return;
      this.render(response);
      if (response.indexing) {
        clearTimeout(this.timer);
        const retryGeneration = ++this.generation;
        this.timer = setTimeout(() => void this.run(query, retryGeneration), 200);
      }
    } catch (error) {
      if (generation !== this.generation || !this.dialog.open) return;
      this.results.replaceChildren();
      this.status.textContent = 'Workspace search failed. See Output for details.';
      this.report(error);
    }
  }

  private render(response: WorkspaceSearchResponse): void {
    this.results.replaceChildren(...response.results.map(result => {
      const button = document.createElement('button');
      button.className = 'workspace-search-row';
      button.type = 'button';
      const primary = document.createElement('span');
      primary.className = 'workspace-search-primary';
      primary.textContent = `${result.path}${result.line > 0 ? `:${result.line}` : ''}`;
      const secondary = document.createElement('span');
      secondary.className = 'workspace-search-preview';
      secondary.textContent = result.preview || result.type;
      const kind = document.createElement('span');
      kind.className = 'workspace-search-kind';
      kind.textContent = result.type.toUpperCase();
      button.append(primary, secondary, kind);
      button.onclick = () => {
        this.dialog.close();
        void this.openResult(result).catch(this.report);
      };
      return button;
    }));
    if (!response.results.length) {
      this.status.textContent = response.indexing ? 'Indexing workspace… search will retry automatically.' : 'No matches.';
    } else {
      this.status.textContent = `${response.results.length} result${response.results.length === 1 ? '' : 's'}${response.indexing ? ' · index still updating' : ''}`;
    }
  }
}

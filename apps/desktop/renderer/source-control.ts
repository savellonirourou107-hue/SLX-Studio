import type { DesktopServices } from '../../../packages/core/services';
import type { GitDiffResponse, GitStatusEntry } from '../../../packages/protocol';

export class SourceControlController {
  private generation = 0;
  private activePath = '';

  constructor(
    private readonly dialog: HTMLDialogElement,
    private readonly summary: HTMLElement,
    private readonly changes: HTMLElement,
    private readonly preview: HTMLElement,
    private readonly refreshButton: HTMLButtonElement,
    private readonly openButton: HTMLButtonElement,
    private readonly files: Pick<DesktopServices, 'gitStatus' | 'gitDiff'>,
    private readonly openPath: (path: string) => Promise<void>,
    private readonly report: (error: unknown) => void,
  ) {
    this.refreshButton.onclick = () => void this.refresh();
    this.openButton.onclick = () => {
      if (!this.activePath) return;
      void this.openPath(this.activePath).then(() => this.dialog.close()).catch(this.report);
    };
    this.dialog.addEventListener('close', () => { ++this.generation; });
  }

  show(): void {
    if (!this.dialog.open) this.dialog.showModal();
    void this.refresh();
  }

  async refresh(): Promise<void> {
    const generation = ++this.generation;
    this.activePath = '';
    this.openButton.disabled = true;
    this.summary.textContent = 'Reading Git status…';
    this.changes.replaceChildren();
    this.preview.replaceChildren(this.message('Select a MATLAB or Simulink change to preview it.'));
    try {
      const status = await this.files.gitStatus();
      if (generation !== this.generation || !this.dialog.open) return;
      if (!status.available) {
        this.summary.textContent = status.detail || 'Workspace is not inside a Git repository.';
        return;
      }
      const branch = status.branch || (status.head ? `detached @ ${status.head.slice(0, 12)}` : 'no commits');
      this.summary.textContent =
        `${branch} · ${status.entries.length} MATLAB/Simulink change${status.entries.length === 1 ? '' : 's'}` +
        (status.ignored_other ? ` · ${status.ignored_other} other path${status.ignored_other === 1 ? '' : 's'} hidden` : '') +
        (status.truncated ? ' · result limit reached' : '');
      this.changes.replaceChildren(...status.entries.map(entry => this.changeButton(entry, generation)));
      if (!status.entries.length) this.changes.append(this.message('No changed .m or .slx files in this workspace.'));
    } catch (error) {
      if (generation !== this.generation) return;
      this.summary.textContent = 'Source control status failed. See Output for details.';
      this.report(error);
    }
  }

  private changeButton(entry: GitStatusEntry, generation: number): HTMLButtonElement {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'source-control-change';
    button.dataset.path = entry.path;
    const status = document.createElement('span');
    status.className = 'source-control-status';
    status.textContent = entry.untracked ? 'U' : `${entry.index === ' ' ? '' : entry.index}${entry.worktree === ' ' ? '' : entry.worktree}` || 'M';
    const path = document.createElement('span');
    path.className = 'source-control-path';
    path.textContent = entry.path;
    const kind = document.createElement('span');
    kind.className = 'source-control-kind';
    kind.textContent = entry.kind === 'matlab' ? 'M' : 'SLX';
    button.append(status, path, kind);
    if (entry.old_path) button.title = `${entry.old_path} → ${entry.path}`;
    button.onclick = () => void this.previewEntry(entry, button, generation);
    return button;
  }

  private async previewEntry(entry: GitStatusEntry, button: HTMLButtonElement, generation: number): Promise<void> {
    for (const candidate of this.changes.querySelectorAll('button')) candidate.classList.remove('selected');
    button.classList.add('selected');
    this.activePath = entry.path;
    this.openButton.disabled = false;
    this.preview.replaceChildren(this.message('Loading bounded diff preview…'));
    try {
      const diff = await this.files.gitDiff(entry.path);
      if (generation !== this.generation || this.activePath !== entry.path || !this.dialog.open) return;
      this.renderDiff(diff);
    } catch (error) {
      if (generation !== this.generation || this.activePath !== entry.path) return;
      this.preview.replaceChildren(this.message('Diff preview failed. See Output for details.'));
      this.report(error);
    }
  }

  private renderDiff(diff: GitDiffResponse): void {
    if (diff.kind === 'text') {
      const pre = document.createElement('pre');
      pre.className = 'source-control-diff';
      pre.textContent = diff.diff || 'No text difference against HEAD.';
      this.preview.replaceChildren(pre);
      return;
    }
    const header = document.createElement('div');
    header.className = 'source-control-model-summary';
    header.append(
      this.metric('Changes', diff.change_count),
      this.metric('Added blocks', diff.added_blocks.length),
      this.metric('Removed blocks', diff.removed_blocks.length),
      this.metric('Changed blocks', diff.changed_blocks.length),
      this.metric('Lines +/−', `${diff.added_lines}/${diff.removed_lines}`),
    );
    const details = document.createElement('div');
    details.className = 'source-control-model-details';
    const sections: Array<[string, readonly string[]]> = [
      ['Added blocks', diff.added_blocks],
      ['Removed blocks', diff.removed_blocks],
      ['Changed blocks', diff.changed_blocks.map(item =>
        `${item.path}${item.parameter_changes.length ? ` · ${item.parameter_changes.join(', ')}` : ''}`)],
    ];
    for (const [title, items] of sections) {
      if (!items.length) continue;
      const section = document.createElement('section');
      const heading = document.createElement('h3'); heading.textContent = title;
      const list = document.createElement('ul');
      for (const item of items) { const row = document.createElement('li'); row.textContent = item; list.append(row); }
      section.append(heading, list); details.append(section);
    }
    if (diff.truncated) details.append(this.message('Detail list reached its safety limit.'));
    this.preview.replaceChildren(header, details);
  }

  private metric(label: string, value: string | number): HTMLElement {
    const card = document.createElement('div');
    const strong = document.createElement('strong'); strong.textContent = String(value);
    const small = document.createElement('small'); small.textContent = label;
    card.append(strong, small);
    return card;
  }

  private message(text: string): HTMLElement {
    const node = document.createElement('p');
    node.className = 'source-control-message';
    node.textContent = text;
    return node;
  }
}

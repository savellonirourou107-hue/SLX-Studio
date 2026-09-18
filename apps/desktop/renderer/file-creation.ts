import type { DesktopServices } from '../../../packages/core/services';

export interface CopySnapshot { path: string; content: string; bom: boolean; }
export interface FileCreationElements {
  dialog: HTMLDialogElement;
  form: HTMLFormElement;
  input: HTMLInputElement;
  title: HTMLElement;
  help: HTMLElement;
  status: HTMLElement;
  submit: HTMLButtonElement;
  cancel: HTMLButtonElement;
}

/** Explicit create-only workflow. No source save, rename, overwrite or execution. */
export class FileCreationController {
  private root: string | null = null;
  private generation = 0;
  private request: { root: string; generation: number; content: string; bom: boolean; source?: string } | null = null;
  private pending = false;

  constructor(
    private readonly ui: FileCreationElements,
    private readonly files: Pick<DesktopServices, 'create'>,
    private readonly snapshot: () => CopySnapshot,
    private readonly isOpenPath: (path: string) => boolean,
    private readonly openCreated: (path: string) => Promise<void>,
    private readonly refresh: () => Promise<void>,
    private readonly log: (message: string) => void,
  ) {
    ui.form.addEventListener('submit', event => { event.preventDefault(); void this.submit(); });
    ui.cancel.addEventListener('click', () => this.cancel());
    ui.dialog.addEventListener('cancel', event => { event.preventDefault(); this.cancel(); });
    ui.dialog.addEventListener('close', () => { if (!this.pending) this.request = null; });
  }

  get active(): boolean { return this.pending || this.ui.dialog.open; }
  get busy(): boolean { return this.pending; }

  setWorkspace(root: string | null): void {
    this.root = root;
    ++this.generation;
    this.request = null;
    if (this.ui.dialog.open) this.ui.dialog.close();
  }

  show(kind: 'new' | 'copy'): void {
    if (!this.root) throw new Error('Open a workspace first');
    if (this.active) throw new Error('Finish or cancel the current file creation first');
    const copy = kind === 'copy' ? this.snapshot() : null;
    this.request = { root: this.root, generation: this.generation, content: copy?.content || '', bom: copy?.bom || false, source: copy?.path };
    this.ui.title.textContent = copy ? 'Save Copy As' : 'New MATLAB File';
    this.ui.help.textContent = copy
      ? `Copies the buffer snapshot of ${copy.path} taken when this dialog opened. The source stays open and is NOT marked saved. Choose a new .m name in an existing workspace folder. No overwrite or execution.`
      : 'Creates an empty UTF-8 .m file in an existing workspace folder. Existing files are never overwritten. No MATLAB code executes.';
    this.ui.input.value = copy ? copy.path.replace(/\.m$/i, '-copy.m') : 'untitled.m';
    this.ui.submit.textContent = copy ? 'Create copy' : 'Create file';
    this.ui.status.textContent = '';
    this.setPending(false);
    this.ui.dialog.showModal();
    this.ui.input.focus();
    this.ui.input.select();
  }

  cancel(): boolean {
    if (this.pending) return false; // A submitted write cannot be pretended away.
    this.request = null;
    if (this.ui.dialog.open) this.ui.dialog.close();
    return true;
  }

  private setPending(value: boolean): void {
    this.pending = value;
    this.ui.input.disabled = value;
    this.ui.submit.disabled = value;
    this.ui.cancel.disabled = value;
    this.ui.form.setAttribute('aria-busy', String(value));
  }

  async submit(): Promise<void> {
    const request = this.request;
    if (this.pending || !request || !this.ui.dialog.open) return;
    if (request.root !== this.root || request.generation !== this.generation) { this.cancel(); return; }
    // Reject ambiguity instead of trimming/rewriting the user's target name.
    const relative = this.ui.input.value.replace(/\\/g, '/');
    if (!relative || relative.length > 4096 || relative !== relative.trim() || !/\.m$/i.test(relative)) {
      this.ui.status.textContent = 'Enter a workspace-relative .m path, for example experiments/controller.m.';
      return;
    }
    if (this.isOpenPath(relative)) {
      this.ui.status.textContent = 'That path already has an open editor. Choose another name; its buffer will not be replaced.';
      return;
    }
    this.setPending(true);
    this.ui.status.textContent = 'Creating file…';
    const current = () => this.root === request.root && this.generation === request.generation;
    try {
      const created = await this.files.create(request.root, relative, request.content, request.bom);
      if (!current()) {
        this.log(`Created ${relative} in the previous workspace; not opened in the current workspace.`);
        return;
      }
      this.request = null;
      this.ui.dialog.close();
      this.log(`Created ${created.path}${request.source ? ` from ${request.source}; source remains unchanged` : ''}.`);
      for (const warning of created.warnings) this.log(warning);
      // Creation succeeded even if opening/refresh fails: never submit it again.
      try { await this.refresh(); } catch (error) { this.log(`File created, but Explorer refresh failed: ${(error as Error).message}`); }
      if (current()) {
        try { await this.openCreated(created.path); }
        catch (error) { this.log(`File created, but could not open ${created.path}: ${(error as Error).message}`); }
      }
    } catch (error) {
      if (current()) this.ui.status.textContent = `${(error as Error).message}. No automatic retry was made.`;
      else this.log(`File creation in the previous workspace failed: ${(error as Error).message}`);
    } finally { this.setPending(false); }
  }
}

import type * as Monaco from 'monaco-editor/editor/editor.api.js';
import type { DesktopServices } from '../core/services';
import type { DocumentSnapshot } from '../protocol';
import { matlabSection } from './sections';

export interface OpenDocument {
  path: string;
  base: DocumentSnapshot;
  cleanValue: string;
  model: Monaco.editor.ITextModel;
  view: Monaco.editor.ICodeEditorViewState | null;
  listener: Monaco.IDisposable;
  timer?: ReturnType<typeof setTimeout>;
  saving?: Promise<void>;
  draftQueue: Promise<unknown>;
}
export type Decision = (title: string, detail: string, options: string[]) => Promise<string>;

export class DocumentEditors {
  readonly documents = new Map<string, OpenDocument>();
  active: OpenDocument | null = null;
  private editor: Monaco.editor.IStandaloneCodeEditor | null = null;
  private monaco: typeof Monaco | null = null;
  private loading: Promise<void> | null = null;
  private opening = new Map<string, Promise<void>>();
  private options = { fontSize: 14, minimap: false };
  constructor(
    private readonly container: HTMLElement,
    private readonly files: DesktopServices,
    private readonly choose: Decision,
    private readonly changed: () => void,
    private readonly log: (text: string) => void,
  ) {}
  configure(options: { fontSize: number; minimap: boolean }): void {
    this.options = { ...options };
    this.editor?.updateOptions({ fontSize: options.fontSize, minimap: { enabled: options.minimap } });
  }
  reveal(path: string, line = 1, column = 1): void {
    const document = this.documents.get(path);
    if (!document || !this.editor) return;
    this.select(path);
    const position = { lineNumber: Math.max(1, Math.min(line, document.model.getLineCount())), column: Math.max(1, column) };
    this.editor.setPosition(position);
    this.editor.revealPositionInCenter(position);
  }
  private async ensureEditor(): Promise<void> {
    if (!this.loading) this.loading = (async () => {
      const { monaco } = await import('./monaco');
      this.monaco = monaco;
      const editor = monaco.editor.create(this.container, {
        theme: 'slx-dark', model: null, automaticLayout: true, fontSize: this.options.fontSize,
        fontFamily: 'Consolas, "Cascadia Code", monospace', minimap: { enabled: this.options.minimap },
        padding: { top: 12 }, scrollBeyondLastLine: false, tabSize: 4,
        ariaLabel: 'MATLAB code editor', fixedOverflowWidgets: true,
      });
      this.editor = editor;
      editor.onDidChangeCursorPosition(() => this.changed());
    })();
    await this.loading;
  }
  dirty(document: OpenDocument): boolean { return document.model.getValue() !== document.cleanValue; }
  async open(path: string): Promise<void> {
    if (this.documents.has(path)) { this.select(path); return; }
    if (this.opening.has(path)) return this.opening.get(path)!;
    const job = this.openNew(path);
    this.opening.set(path, job);
    try { await job; } finally { this.opening.delete(path); }
  }
  private async openNew(path: string): Promise<void> {
    const base = await this.files.read(path);
    await this.ensureEditor();
    const model = this.monaco!.editor.createModel(base.content, 'matlab', this.monaco!.Uri.from({ scheme: 'slx-file', path: `/${path}` }));
    if (base.eol === 'CRLF') model.setEOL(this.monaco!.editor.EndOfLineSequence.CRLF);
    // Mixed newline files are read-only until a deliberate normalization design exists.
    if (base.mixed_eol) this.log(`${path}: mixed line endings; opened read-only to avoid silent conversion.`);
    const document: OpenDocument = { path, base, cleanValue: model.getValue(), model, view: null, listener: { dispose() {} }, draftQueue: Promise.resolve() };
    this.documents.set(path, document);
    document.listener = model.onDidChangeContent(() => {
      this.changed();
      clearTimeout(document.timer);
      document.timer = setTimeout(() => void this.persistDraft(document).catch(error => this.log(`Draft not saved: ${error.message}`)), 300);
    });
    this.select(path);
    try {
      const draft = await this.files.draft(path);
      if (draft && draft.content !== base.content) {
        const answer = await this.choose('Recovery draft available', `${path}\n${draft.base.sha256 === base.sha256 ? 'An unsaved draft is available.' : 'The disk file changed since this draft. Restoring will not overwrite the disk; saving will require resolving the conflict.'}`, ['Keep disk', 'Restore draft']);
        if (answer === 'Restore draft') {
          document.base = draft.base;
          model.setEOL(draft.base.eol === 'CRLF' ? this.monaco!.editor.EndOfLineSequence.CRLF : this.monaco!.editor.EndOfLineSequence.LF);
          document.cleanValue = draft.base.content.replace(/\r\n|\r|\n/g, draft.base.eol === 'CRLF' ? '\r\n' : '\n');
          model.setValue(draft.content);
        } else if (answer === 'Keep disk') await this.files.clearDraft(path);
      }
    } catch (error) { this.log(`Recovery: ${(error as Error).message}`); }
    this.changed();
  }
  select(path: string): void {
    const document = this.documents.get(path);
    if (!document || !this.editor) return;
    if (this.active) this.active.view = this.editor.saveViewState();
    this.active = document;
    this.editor.setModel(document.model);
    this.editor.updateOptions({ readOnly: document.base.mixed_eol });
    if (document.view) this.editor.restoreViewState(document.view);
    this.container.hidden = false;
    this.editor.layout();
    this.editor.focus();
    this.changed();
  }
  private persistDraft(document: OpenDocument, clear = false): Promise<unknown> {
    clearTimeout(document.timer);
    const content = document.model.getValue();
    const base = { ...document.base };
    const clean = !this.dirty(document);
    const job = document.draftQueue.catch(() => {}).then(() => clear || clean
      ? this.files.clearDraft(document.path)
      : this.files.keepDraft({ path: document.path, content, base }));
    document.draftQueue = job;
    return job;
  }
  async save(document = this.active): Promise<void> {
    if (!document || !this.dirty(document)) return;
    if (document.base.mixed_eol) throw new Error('Mixed line endings: save is disabled to preserve the original bytes.');
    if (document.saving) { await document.saving; return this.save(document); }
    const content = document.model.getValue();
    const job = (async () => {
      try {
        const saved = await this.files.save(document.base, content);
        document.base = saved;
        document.cleanValue = saved.content;
        this.log(`Saved ${document.path}`);
        await this.persistDraft(document);
      } catch (error) {
        this.log(`Save failed: ${(error as Error).message}`);
        throw error;
      } finally { this.changed(); }
    })();
    document.saving = job;
    try { await job; } finally { document.saving = undefined; }
  }
  async close(path: string): Promise<boolean> {
    const document = this.documents.get(path);
    if (!document) return true;
    if (document.saving) { try { await document.saving; } catch { return false; } }
    if (this.dirty(document)) {
      const answer = await this.choose('Unsaved changes', `Save changes to ${path}?`, ['Cancel', 'Discard', 'Save']);
      if (answer === 'Cancel') return false;
      if (answer === 'Save') {
        try { await this.save(document); } catch { return false; }
        if (this.dirty(document)) return false;
      }
    }
    await this.persistDraft(document, true);
    document.listener.dispose();
    this.documents.delete(path);
    if (this.active === document) { this.active = null; this.editor?.setModel(null); }
    document.model.dispose();
    if (!this.active && this.documents.size) this.select(this.documents.keys().next().value!);
    if (!this.documents.size) this.container.hidden = true;
    this.changed();
    return true;
  }
  async closeAll(): Promise<boolean> {
    for (const path of [...this.documents.keys()]) if (!await this.close(path)) return false;
    return true;
  }
  async reload(): Promise<void> {
    if (!this.active) return;
    const document = this.active;
    if (this.dirty(document) && await this.choose('Reload from disk', 'Discard the current editor changes and read the disk version?', ['Cancel', 'Reload']) !== 'Reload') return;
    const fresh = await this.files.read(document.path);
    document.base = fresh;
    document.model.setValue(fresh.content);
    document.model.setEOL(fresh.eol === 'CRLF' ? this.monaco!.editor.EndOfLineSequence.CRLF : this.monaco!.editor.EndOfLineSequence.LF);
    document.cleanValue = document.model.getValue();
    await this.persistDraft(document, true);
    this.editor?.updateOptions({ readOnly: fresh.mixed_eol });
    this.changed();
  }
  position(): string {
    const position = this.editor?.getPosition();
    return this.active && position ? `Ln ${position.lineNumber}, Col ${position.column} · ${this.active.base.eol} · MATLAB (syntax only)` : 'Ready';
  }
  section(): { path: string; code: string; startLine: number; endLine: number } {
    if (!this.active || !this.editor) throw new Error('Open a MATLAB file first');
    return { path: this.active.path, ...matlabSection(this.active.model.getValue(), this.editor.getPosition()?.lineNumber || 1) };
  }
}

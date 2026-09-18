import type * as Monaco from 'monaco-editor/editor/editor.api.js';
import type { DesktopServices } from '../core/services';
import type { DocumentSnapshot } from '../protocol';
import { matlabSection } from './sections';

export interface OpenDocument {
  path: string;
  base: DocumentSnapshot;
  cleanAlternativeVersionId: number;
  model: Monaco.editor.ITextModel;
  view: Monaco.editor.ICodeEditorViewState | null;
  listener: Monaco.IDisposable;
  timer?: ReturnType<typeof setTimeout>;
  recoveryPending: boolean;
  operations: Promise<unknown>;
  closing?: Promise<boolean>;
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
  private generation = 0;
  private closingAll: Promise<boolean> | null = null;
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
        wordBasedSuggestions: 'off',
      });
      this.editor = editor;
      editor.onDidChangeCursorPosition(() => this.changed());
    })();
    await this.loading;
  }
  dirty(document: OpenDocument): boolean { return document.model.getAlternativeVersionId() !== document.cleanAlternativeVersionId; }
  private isOpen(document: OpenDocument): boolean {
    return this.documents.get(document.path) === document && !document.model.isDisposed();
  }
  // Serialize explicit file operations, not keystrokes. A later operation may
  // proceed after an earlier failure, but failed writes are never replayed.
  private enqueue<T>(document: OpenDocument, operation: () => Promise<T>): Promise<T> {
    const job = document.operations.catch(() => {}).then(operation);
    document.operations = job;
    return job;
  }
  async open(path: string): Promise<void> {
    if (this.closingAll) throw new Error('Editors are closing; open the file again after the transition.');
    if (this.documents.has(path)) { this.select(path); return; }
    if (this.opening.has(path)) return this.opening.get(path)!;
    const job = this.openNew(path, this.generation);
    this.opening.set(path, job);
    try { await job; } finally { this.opening.delete(path); }
  }
  private async openNew(path: string, generation: number): Promise<void> {
    const base = await this.files.read(path);
    if (generation !== this.generation) return;
    await this.ensureEditor();
    if (generation !== this.generation) return;
    const model = this.monaco!.editor.createModel(base.content, 'matlab', this.monaco!.Uri.from({ scheme: 'slx-file', path: `/${path}` }));
    if (base.eol === 'CRLF') model.setEOL(this.monaco!.editor.EndOfLineSequence.CRLF);
    // Mixed newline files are read-only until a deliberate normalization design exists.
    if (base.mixed_eol) this.log(`${path}: mixed line endings; opened read-only to avoid silent conversion.`);
    const document: OpenDocument = { path, base, cleanAlternativeVersionId: model.getAlternativeVersionId(), model, view: null, listener: { dispose() {} }, draftQueue: Promise.resolve(), recoveryPending: true, operations: Promise.resolve() };
    this.documents.set(path, document);
    document.listener = model.onDidChangeContent(() => {
      this.changed();
      clearTimeout(document.timer);
      document.timer = setTimeout(() => void this.persistDraft(document).catch(error => this.log(`Draft not saved: ${error.message}`)), 300);
    });
    this.select(path);
    const initialVersion = model.getVersionId();
    const mayRecover = () => generation === this.generation && this.isOpen(document)
      && !document.closing && document.base === base && model.getVersionId() === initialVersion;
    try {
      const draft = await this.files.draft(path);
      if (!mayRecover()) return;
      if (draft && draft.content !== base.content) {
        const answer = await this.choose('Recovery draft available', `${path}\n${draft.base.sha256 === base.sha256 ? 'An unsaved draft is available.' : 'The disk file changed since this draft. Restoring will not overwrite the disk; saving will require resolving the conflict.'}`, ['Keep disk', 'Restore draft']);
        if (!mayRecover()) return;
        if (answer === 'Restore draft') {
          document.recoveryPending = false;
          document.base = draft.base;
          const cleanContent = draft.base.content.replace(/\r\n|\r|\n/g, draft.base.eol === 'CRLF' ? '\r\n' : '\n');
          model.setValue(cleanContent);
          model.setEOL(draft.base.eol === 'CRLF' ? this.monaco!.editor.EndOfLineSequence.CRLF : this.monaco!.editor.EndOfLineSequence.LF);
          document.cleanAlternativeVersionId = model.getAlternativeVersionId();
          model.setValue(draft.content);
          if (this.active === document) this.editor?.updateOptions({ readOnly: document.base.mixed_eol });
        } else if (answer === 'Keep disk') {
          document.recoveryPending = false;
          await this.persistDraft(document, true);
        }
      } else document.recoveryPending = false;
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
    if (!this.isOpen(document)) return Promise.resolve();
    const content = document.model.getValue();
    const base = { ...document.base };
    const clean = !this.dirty(document);
    // Closing a clean tab before recovery is decided must not delete an older
    // unsaved draft that the user has never seen or chosen to discard.
    if (clean && document.recoveryPending) return document.draftQueue;
    const job = document.draftQueue.catch(() => {}).then(() => clear || clean
      ? this.files.clearDraft(document.path)
      : this.files.keepDraft({ path: document.path, content, base }));
    document.draftQueue = job;
    return job;
  }
  async save(document = this.active): Promise<void> {
    if (!document) return;
    await this.enqueue(document, () => this.saveDocument(document));
  }
  copySnapshot(): { path: string; content: string; bom: boolean } {
    const document = this.active;
    if (!document || !this.isOpen(document) || document.closing || this.closingAll) throw new Error('Open a MATLAB document first');
    if (document.base.mixed_eol) throw new Error('Mixed line endings: copying the normalized editor buffer is disabled to protect the original bytes.');
    return { path: document.path, content: document.model.getValue(), bom: document.base.bom };
  }
  async saveAll(): Promise<void> {
    // One pass: never chase a user who keeps typing, and stop at the first
    // failure rather than silently claiming that the entire workspace saved.
    for (const document of [...this.documents.values()]) await this.save(document);
  }
  private async saveDocument(document: OpenDocument): Promise<void> {
    if (!this.isOpen(document) || !this.dirty(document)) return;
    if (document.base.mixed_eol) throw new Error('Mixed line endings: save is disabled to preserve the original bytes.');
    // A saved version must also be a reachable undo stop. Otherwise subsequent
    // typing can merge with the previous edit and undo skips the saved state.
    document.model.pushStackElement();
    const content = document.model.getValue();
    const savedAlternativeVersionId = document.model.getAlternativeVersionId();
    try {
      let saved: DocumentSnapshot;
      try {
        saved = await this.files.save(document.base, content);
      } catch (error) {
        this.log(`Save failed: ${(error as Error).message}`);
        throw error;
      }
      document.base = saved;
      // Only the version actually written becomes clean; newer typing stays dirty.
      document.cleanAlternativeVersionId = savedAlternativeVersionId;
      this.log(`Saved ${document.path}`);
      try {
        await this.persistDraft(document);
      } catch (error) {
        this.log(`File saved, but recovery draft update failed: ${(error as Error).message}`);
        throw error;
      }
    } finally { this.changed(); }
  }
  async close(path: string): Promise<boolean> {
    const document = this.documents.get(path);
    if (!document) return true;
    if (document.closing) return document.closing;
    const job = this.enqueue(document, () => this.closeDocument(document));
    document.closing = job;
    try { return await job; } finally { document.closing = undefined; }
  }
  private async closeDocument(document: OpenDocument): Promise<boolean> {
    if (!this.isOpen(document)) return true;
    if (this.dirty(document)) {
      const version = document.model.getVersionId();
      const answer = await this.choose('Unsaved changes', `Save changes to ${document.path}?`, ['Cancel', 'Discard', 'Save']);
      // Dismissed/unknown decisions are never permission to discard work.
      if (answer !== 'Discard' && answer !== 'Save') return false;
      if (document.model.getVersionId() !== version) return false;
      if (answer === 'Save') {
        try { await this.saveDocument(document); } catch { return false; }
        if (this.dirty(document)) return false;
      }
    }
    const closingVersion = document.model.getVersionId();
    try {
      await this.persistDraft(document, true);
      if (document.model.getVersionId() !== closingVersion) {
        await this.persistDraft(document);
        this.log(`Close canceled: ${document.path} changed while closing.`);
        return false;
      }
    } catch (error) {
      this.log(`Close canceled: recovery draft update failed: ${(error as Error).message}`);
      return false;
    }
    clearTimeout(document.timer);
    document.listener.dispose();
    this.documents.delete(document.path);
    if (this.active === document) { this.active = null; this.editor?.setModel(null); }
    document.model.dispose();
    if (!this.active && this.documents.size) this.select(this.documents.keys().next().value!);
    if (!this.documents.size) this.container.hidden = true;
    this.changed();
    return true;
  }
  async closeAll(): Promise<boolean> {
    if (this.closingAll) return this.closingAll;
    // Invalidate reads from the old workspace before waiting on them. In-flight
    // recovery must settle before any workspace switch can reuse a relative URI.
    this.generation += 1;
    const job = (async () => {
      await Promise.allSettled([...this.opening.values()]);
      for (const path of [...this.documents.keys()]) if (!await this.close(path)) return false;
      return true;
    })();
    this.closingAll = job;
    try { return await job; } finally { this.closingAll = null; }
  }
  async reload(): Promise<void> {
    const document = this.active;
    if (!document) return;
    await this.enqueue(document, async () => {
      if (!this.isOpen(document)) return;
      const version = document.model.getVersionId();
      if (this.dirty(document) && await this.choose('Reload from disk', 'Discard the current editor changes and read the disk version?', ['Cancel', 'Reload']) !== 'Reload') return;
      if (document.model.getVersionId() !== version) {
        this.log(`Reload canceled: ${document.path} changed while confirming.`);
        return;
      }
      const fresh = await this.files.read(document.path);
      // Never apply a stale read over edits made while IO was in flight. A
      // monotonic version also detects edit-then-undo during the read.
      if (!this.isOpen(document) || document.model.getVersionId() !== version) {
        this.log(`Reload canceled: ${document.path} changed while reading.`);
        return;
      }
      document.base = fresh;
      document.model.setValue(fresh.content);
      document.model.setEOL(fresh.eol === 'CRLF' ? this.monaco!.editor.EndOfLineSequence.CRLF : this.monaco!.editor.EndOfLineSequence.LF);
      document.cleanAlternativeVersionId = document.model.getAlternativeVersionId();
      if (this.active === document) this.editor?.updateOptions({ readOnly: fresh.mixed_eol });
      await this.persistDraft(document);
      this.changed();
    });
  }
  position(): string {
    const position = this.editor?.getPosition();
    return this.active && position ? `Ln ${position.lineNumber}, Col ${position.column} · ${this.active.base.eol} · MATLAB (lightweight assistance, not LSP)` : 'Ready';
  }
  section(): { path: string; code: string; startLine: number; endLine: number } {
    if (!this.active || !this.editor) throw new Error('Open a MATLAB file first');
    return { path: this.active.path, ...matlabSection(this.active.model.getValue(), this.editor.getPosition()?.lineNumber || 1) };
  }
}

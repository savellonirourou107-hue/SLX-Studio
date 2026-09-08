export interface CustomEditorContribution {
  id: string;
  label: string;
  extensions: readonly string[];
  priority?: number;
  open(path: string): void | Promise<void>;
}

export class CustomEditorRegistry {
  private readonly entries = new Map<string, CustomEditorContribution>();
  register(editor: CustomEditorContribution): () => void {
    if (!editor || typeof editor.id !== 'string' || !/^[a-z][a-zA-Z0-9]*(?:\.[a-zA-Z][a-zA-Z0-9]*)+$/.test(editor.id) || typeof editor.label !== 'string' || !editor.label.trim() || !Array.isArray(editor.extensions) || !editor.extensions.length || editor.extensions.some(extension => typeof extension !== 'string' || !/^\.[a-z0-9][a-z0-9-]{0,15}$/i.test(extension)) || typeof editor.open !== 'function' || this.entries.has(editor.id)) throw new Error(`Invalid or duplicate custom editor: ${editor?.id}`);
    const entry = Object.freeze({ ...editor, extensions: Object.freeze([...editor.extensions]), priority: editor.priority ?? 0 });
    this.entries.set(entry.id, entry);
    return () => { if (this.entries.get(entry.id) === entry) this.entries.delete(entry.id); };
  }
  resolve(path: string): CustomEditorContribution | undefined {
    const extension = path.slice(path.lastIndexOf('.')).toLowerCase();
    return [...this.entries.values()].filter(editor => editor.extensions.some(item => item.toLowerCase() === extension)).sort((a, b) => (b.priority ?? 0) - (a.priority ?? 0))[0];
  }
  list(): readonly CustomEditorContribution[] { return [...this.entries.values()]; }
}

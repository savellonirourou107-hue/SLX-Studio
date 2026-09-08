export type ViewLocation = 'activity' | 'sidebar' | 'panel';
export interface ViewContribution { id: string; title: string; location: ViewLocation; }
export interface OutputEntry { text: string; level: 'info' | 'warning' | 'error'; at: number; }
export interface Problem { path: string; message: string; severity: 'info' | 'warning' | 'error'; line?: number; column?: number; source?: string; }
type Listener<T> = (value: T) => void;

export class ViewRegistry {
  private readonly entries = new Map<string, ViewContribution>();
  register(view: ViewContribution): () => void {
    if (!view || typeof view.id !== 'string' || !/^[a-z][a-zA-Z0-9]*(?:\.[a-zA-Z][a-zA-Z0-9]*)+$/.test(view.id) || typeof view.title !== 'string' || !view.title.trim() || !['activity', 'sidebar', 'panel'].includes(view.location) || this.entries.has(view.id)) throw new Error(`Invalid or duplicate view: ${view?.id}`);
    const entry = Object.freeze({ ...view });
    this.entries.set(entry.id, entry);
    return () => { if (this.entries.get(entry.id) === entry) this.entries.delete(entry.id); };
  }
  list(): readonly ViewContribution[] { return [...this.entries.values()]; }
}

export class OutputService {
  private readonly entries: OutputEntry[] = [];
  private readonly listeners = new Set<Listener<readonly OutputEntry[]>>();
  constructor(private readonly maxEntries = 1000, private readonly maxChars = 65_536) {
    if (!Number.isInteger(maxEntries) || maxEntries < 1 || !Number.isInteger(maxChars) || maxChars < 1) throw new Error('Output limits must be positive integers');
  }
  append(text: string, level: OutputEntry['level'] = 'info'): void {
    if (typeof text !== 'string' || !text) throw new Error('Output text must be non-empty');
    const bounded = text.length > this.maxChars ? `${text.slice(0, this.maxChars - 1)}…` : text;
    this.entries.push({ text: bounded, level, at: Date.now() });
    while (this.entries.length > this.maxEntries) this.entries.shift();
    let total = this.entries.reduce((size, entry) => size + entry.text.length, 0);
    while (total > this.maxChars && this.entries.length > 1) total -= this.entries.shift()!.text.length;
    this.emit();
  }
  clear(): void { this.entries.length = 0; this.emit(); }
  snapshot(): readonly OutputEntry[] { return this.entries.map(entry => ({ ...entry })); }
  subscribe(listener: Listener<readonly OutputEntry[]>): () => void { this.listeners.add(listener); return () => this.listeners.delete(listener); }
  private emit(): void { const snapshot = this.snapshot(); for (const listener of this.listeners) listener(snapshot); }
}

export class ProblemsService {
  private readonly problems: Problem[] = [];
  private readonly listeners = new Set<Listener<readonly Problem[]>>();
  constructor(private readonly maxProblems = 1000) {
    if (!Number.isInteger(maxProblems) || maxProblems < 1) throw new Error('Problem limit must be a positive integer');
  }
  replace(problems: readonly Problem[]): void {
    if (problems.some(problem => !problem.path || !problem.message || !['info', 'warning', 'error'].includes(problem.severity))) throw new Error('Invalid problem');
    this.problems.splice(0, this.problems.length, ...problems.slice(0, this.maxProblems).map(problem => ({ ...problem, message: problem.message.slice(0, 8_192) })));
    this.emit();
  }
  clear(): void { this.problems.length = 0; this.emit(); }
  snapshot(): readonly Problem[] { return this.problems.map(problem => ({ ...problem })); }
  subscribe(listener: Listener<readonly Problem[]>): () => void { this.listeners.add(listener); return () => this.listeners.delete(listener); }
  private emit(): void { const snapshot = this.snapshot(); for (const listener of this.listeners) listener(snapshot); }
}

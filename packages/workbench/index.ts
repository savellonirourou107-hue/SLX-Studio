export type ViewLocation = 'activity' | 'sidebar' | 'panel';
export interface ViewContribution { id: string; title: string; location: ViewLocation; }
export interface OutputEntry { text: string; level: 'info' | 'warning' | 'error'; at: number; stream?: boolean; }
export interface Problem { path: string; message: string; severity: 'info' | 'warning' | 'error'; line?: number; column?: number; source?: string; }
type Listener<T> = (value: T) => void;
export interface Disposable { dispose(): void; }
export interface WorkbenchContributionContext {
  add(resource: Disposable | (() => void)): void;
}
export interface WorkbenchContribution {
  id: string;
  activate(context: WorkbenchContributionContext): void | Promise<void>;
}

/** Owns contribution registrations so activation failures cannot leak listeners. */
export class WorkbenchContributionRegistry {
  private readonly definitions = new Map<string, WorkbenchContribution>();
  private readonly active = new Map<string, WorkbenchContributionContextImpl>();
  private readonly states = new Map<string, 'inactive' | 'activating' | 'active' | 'failed'>();
  private readonly activations = new Map<string, Promise<void>>();
  register(contribution: WorkbenchContribution): () => void {
    if (!contribution || typeof contribution.id !== 'string' || !/^[a-z][a-zA-Z0-9]*(?:\.[a-zA-Z][a-zA-Z0-9]*)+$/.test(contribution.id) || typeof contribution.activate !== 'function' || this.definitions.has(contribution.id)) throw new Error(`Invalid or duplicate contribution: ${contribution?.id}`);
    const entry = Object.freeze({ ...contribution });
    this.definitions.set(entry.id, entry);
    this.states.set(entry.id, 'inactive');
    return () => {
      if (this.definitions.get(entry.id) !== entry) return;
      const context = this.active.get(entry.id);
      this.active.delete(entry.id);
      context?.dispose();
      this.states.delete(entry.id);
      this.definitions.delete(entry.id);
    };
  }
  async activate(id: string): Promise<void> {
    const contribution = this.definitions.get(id);
    if (!contribution) throw new Error(`Unknown contribution: ${id}`);
    if (this.active.has(id)) return;
    const pending = this.activations.get(id);
    if (pending) return pending;
    const operation = this.activateOnce(id, contribution);
    this.activations.set(id, operation);
    try { await operation; } finally { if (this.activations.get(id) === operation) this.activations.delete(id); }
  }
  private async activateOnce(id: string, contribution: WorkbenchContribution): Promise<void> {
    const context = new WorkbenchContributionContextImpl();
    this.states.set(id, 'activating');
    try {
      await contribution.activate(context);
      if (this.definitions.get(id) !== contribution || this.states.get(id) !== 'activating') {
        context.dispose();
        return;
      }
      this.active.set(id, context);
      this.states.set(id, 'active');
    } catch (error) {
      // Keep the activation failure as the public error even when a partially
      // registered resource also fails to dispose. The context still attempts
      // every cleanup callback before returning here.
      try { context.dispose(); } catch { /* preserve the activation error */ }
      if (this.definitions.get(id) === contribution && this.states.get(id) === 'activating') this.states.set(id, 'failed');
      throw error;
    }
  }
  deactivate(id: string): void {
    if (!this.definitions.has(id)) throw new Error(`Unknown contribution: ${id}`);
    const context = this.active.get(id);
    this.active.delete(id);
    this.states.set(id, 'inactive');
    context?.dispose();
  }
  list(): readonly { id: string; state: 'inactive' | 'activating' | 'active' | 'failed' }[] {
    return [...this.definitions.keys()].map(id => ({ id, state: this.states.get(id)! }));
  }
}

class WorkbenchContributionContextImpl implements WorkbenchContributionContext {
  private readonly resources: (() => void)[] = [];
  private disposed = false;
  add(resource: Disposable | (() => void)): void {
    if (this.disposed) throw new Error('Contribution context is disposed');
    const dispose = typeof resource === 'function' ? resource : resource?.dispose?.bind(resource);
    if (typeof dispose !== 'function') throw new Error('Contribution resource must be disposable');
    this.resources.push(dispose);
  }
  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    let failure: unknown;
    for (const dispose of this.resources.splice(0).reverse()) {
      try { dispose(); } catch (error) { failure ||= error; }
    }
    if (failure) throw failure;
  }
}

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
  appendChunk(text: string, level: OutputEntry['level'] = 'info'): void {
    if (typeof text !== 'string' || !text) return;
    const last = this.entries[this.entries.length - 1];
    if (last?.stream && last.level === level) {
      last.text = (last.text + text).slice(-this.maxChars);
      let total = this.entries.reduce((size, entry) => size + entry.text.length, 0);
      while (total > this.maxChars && this.entries.length > 1) total -= this.entries.shift()!.text.length;
    } else {
      this.append(text.slice(-this.maxChars), level);
      this.entries[this.entries.length - 1].stream = true;
    }
    this.emit();
  }
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

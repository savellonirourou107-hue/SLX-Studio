export interface Command { id: string; title: string; enabled?: () => boolean; run: () => unknown | Promise<unknown>; }

export class CommandRegistry {
  private readonly entries = new Map<string, Command>();
  register(command: Command): () => void {
    if (!command || typeof command.id !== 'string' || command.id.length > 128 || !/^[a-z][a-zA-Z0-9]*(?:\.[a-zA-Z][a-zA-Z0-9]*)+$/.test(command.id) || this.entries.has(command.id)) throw new Error(`Invalid or duplicate command: ${command?.id}`);
    if (typeof command.title !== 'string' || !command.title.trim() || command.title.length > 256 || typeof command.run !== 'function' || (command.enabled !== undefined && typeof command.enabled !== 'function')) throw new Error('Invalid command definition');
    const registered = Object.freeze({ ...command });
    this.entries.set(command.id, registered);
    return () => { if (this.entries.get(registered.id) === registered) this.entries.delete(registered.id); };
  }
  list(): Command[] { return [...this.entries.values()]; }
  async execute(id: string): Promise<void> {
    const command = this.entries.get(id);
    if (!command) throw new Error(`Unknown command: ${id}`);
    if (command.enabled && !command.enabled()) throw new Error(`Command unavailable: ${command.title}`);
    await command.run();
  }
}

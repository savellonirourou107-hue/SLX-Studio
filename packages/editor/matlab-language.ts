/** Bounded lexical helpers; no cross-file, class, path or workspace-type semantics. */
export const MAX_SYMBOL_SOURCE_CHARS = 250_000;
export const MAX_LOCAL_SYMBOLS = 1000;
export interface LocalSymbol { name: string; kind: 'variable' | 'function' | 'parameter'; line: number }

export function matlabCode(source: string): { code: string; inNonCode: boolean } {
  const out = source.split(''); // Preserve UTF-16 offsets used by Monaco, including astral characters.
  let state: 'code' | 'line' | 'block' | 'single' | 'double' = 'code';
  for (let i = 0; i < source.length; i++) {
    const char = source[i];
    if (char === '\n') {
      if (state !== 'block') state = 'code';
      continue;
    }
    if (state === 'block') {
      out[i] = ' ';
      if (char === '%' && source[i + 1] === '}') { out[++i] = ' '; state = 'code'; }
    } else if (state === 'line') out[i] = ' ';
    else if (state === 'single' || state === 'double') {
      const quote = state === 'single' ? "'" : '"';
      out[i] = ' ';
      if (char === quote) {
        if (source[i + 1] === quote) out[++i] = ' ';
        else state = 'code';
      }
    } else if (char === '%') {
      out[i] = ' ';
      if (source[i + 1] === '{') { state = 'block'; out[++i] = ' '; }
      else state = 'line';
    } else if (char === '.' && source.slice(i, i + 3) === '...') {
      state = 'line'; out[i] = ' ';
    } else if (char === '"' || (char === "'" && !/[\w)\]}.]/.test(source[i - 1] || ' '))) {
      state = char === '"' ? 'double' : 'single'; out[i] = ' ';
    }
  }
  return { code: out.join(''), inNonCode: state !== 'code' };
}

export function extractMatlabSymbols(source: string): LocalSymbol[] {
  if (source.length > MAX_SYMBOL_SOURCE_CHARS) return [];
  const { code } = matlabCode(source);
  const found = new Map<string, LocalSymbol>();
  const add = (name: string, kind: LocalSymbol['kind'], line: number) => {
    if (/^[A-Za-z]\w*$/.test(name) && found.size < MAX_LOCAL_SYMBOLS) {
      if (!found.has(name) || kind === 'function') found.set(name, { name, kind, line });
    }
  };
  code.split('\n').forEach((text, index) => {
    const declaration = /^\s*function\s+(?:(\[[^\]]*\]|[A-Za-z]\w*)\s*=\s*)?([A-Za-z]\w*)\s*(?:\(([^)]*)\))?/.exec(text);
    if (declaration) {
      add(declaration[2], 'function', index + 1);
      for (const name of (declaration[1] || '').match(/[A-Za-z]\w*/g) || []) add(name, 'variable', index + 1);
      for (const name of (declaration[3] || '').split(',')) add(name.trim(), 'parameter', index + 1);
    }
    const iterator = /(?:^|[;,])\s*(?:for|parfor)\s+([A-Za-z]\w*)\s*=/.exec(text);
    if (iterator) add(iterator[1], 'variable', index + 1);
    for (const match of text.matchAll(/(?:^|[;,])\s*([A-Za-z]\w*)\s*=(?!=)/g)) add(match[1], 'variable', index + 1);
    const tuple = /^\s*\[([^\]]+)\]\s*=(?!=)/.exec(text);
    if (tuple) for (const name of tuple[1].split(/[,\s]+/)) add(name, 'variable', index + 1);
  });
  return [...found.values()];
}

export function matlabCallContext(prefix: string): { name: string; parameter: number } | null {
  const { code, inNonCode } = matlabCode(prefix);
  if (inNonCode) return null;
  const stack: { close: string; name?: string; parameter: number }[] = [];
  for (let i = 0; i < code.length; i++) {
    const char = code[i];
    if ('([{'.includes(char)) {
      const match = char === '(' ? /([A-Za-z]\w*)\s*$/.exec(code.slice(0, i)) : null;
      const name = match && code[match.index - 1] !== '.' ? match[1] : undefined;
      stack.push({ close: char === '(' ? ')' : char === '[' ? ']' : '}', name, parameter: 0 });
    } else if (')]}'.includes(char)) {
      if (stack.at(-1)?.close === char) stack.pop();
      else return null;
    } else if (char === ',' && stack.at(-1)?.close === ')') stack.at(-1)!.parameter++;
  }
  const frame = [...stack].reverse().find(item => item.name);
  return frame?.name ? { name: frame.name, parameter: frame.parameter } : null;
}

interface Disposable { dispose(): void }
export interface LexicalModel {
  getValue(): string;
  getValueLength(): number;
  getVersionId(): number;
  onDidChangeContent(listener: () => void): Disposable;
  onWillDispose(listener: () => void): Disposable;
}

/** One scan on open, then at most one per 200 ms quiet period. Reads never scan. */
export class MatlabSymbolCache {
  private entries = new Map<LexicalModel, { version: number; symbols: LocalSymbol[]; timer?: ReturnType<typeof setTimeout>; listeners: Disposable[] }>();
  constructor(private readonly delay = 200) {}
  get size(): number { return this.entries.size; }
  track(model: LexicalModel): void {
    if (this.entries.has(model)) return;
    const entry = { version: -1, symbols: [] as LocalSymbol[], listeners: [] as Disposable[], timer: undefined as ReturnType<typeof setTimeout> | undefined };
    const update = () => {
      const version = model.getVersionId();
      if (entry.version === version) return;
      entry.symbols = model.getValueLength() <= MAX_SYMBOL_SOURCE_CHARS ? extractMatlabSymbols(model.getValue()) : [];
      entry.version = version;
    };
    this.entries.set(model, entry);
    entry.listeners.push(model.onDidChangeContent(() => {
      clearTimeout(entry.timer); entry.timer = setTimeout(update, this.delay);
    }), model.onWillDispose(() => this.release(model)));
    update();
  }
  read(model: LexicalModel): readonly LocalSymbol[] { return this.entries.get(model)?.symbols || []; }
  private release(model: LexicalModel): void {
    const entry = this.entries.get(model);
    if (!entry) return;
    clearTimeout(entry.timer);
    entry.listeners.forEach(listener => listener.dispose());
    this.entries.delete(model);
  }
  dispose(): void { for (const model of this.entries.keys()) this.release(model); }
}

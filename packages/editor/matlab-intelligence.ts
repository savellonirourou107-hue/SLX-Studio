import type * as Monaco from 'monaco-editor/editor/editor.api.js';
import { MATLAB_CATALOG, MATLAB_SYMBOLS } from './matlab-catalog';
import { MatlabSymbolCache, matlabCallContext, matlabCode } from './matlab-language';

export function registerMatlabIntelligence(monaco: typeof Monaco) {
  const cache = new MatlabSymbolCache();
  const track = (model: Monaco.editor.ITextModel) => { if (model.getLanguageId() === 'matlab') cache.track(model); };
  monaco.editor.getModels().forEach(track);
  // Provider context reads are bounded, independently of the debounced symbol scan.
  const prefix = (model: Monaco.editor.ITextModel, position: Monaco.Position) => {
    const offset = model.getOffsetAt(position);
    const start = model.getPositionAt(Math.max(0, offset - 12_000));
    return model.getValueInRange(new monaco.Range(start.lineNumber, start.column, position.lineNumber, position.column));
  };
  const localAt = (model: Monaco.editor.ITextModel, name: string) => cache.read(model).find(item => item.name === name);
  const disposables: Monaco.IDisposable[] = [
    monaco.editor.onDidCreateModel(track),
    monaco.languages.registerCompletionItemProvider('matlab', {
      provideCompletionItems(model, position) {
        const before = prefix(model, position);
        if (matlabCode(before).inNonCode || /\.\w*$/.test(before)) return { suggestions: [] };
        const word = model.getWordUntilPosition(position);
        const range = new monaco.Range(position.lineNumber, word.startColumn, position.lineNumber, word.endColumn);
        const locals = cache.read(model);
        const localNames = new Set(locals.map(item => item.name));
        return { suggestions: [
          ...locals.map(item => ({ label: item.name, insertText: item.name, range,
            kind: item.kind === 'function' ? monaco.languages.CompletionItemKind.Function : monaco.languages.CompletionItemKind.Variable,
            detail: `Current document · lexical ${item.kind} · line ${item.line}`, sortText: `0_${item.name}`,
          })),
          ...MATLAB_CATALOG.filter(item => !localNames.has(item.name)).map(item => ({ label: item.name, insertText: item.name, range,
            kind: monaco.languages.CompletionItemKind.Function, detail: item.product, sortText: `1_${item.name}`,
            documentation: { value: `${item.documentation}\n\nRequires: ${item.product}. Offline catalog; availability not checked.`, isTrusted: false },
          })),
        ] };
      },
    }),
    monaco.languages.registerHoverProvider('matlab', {
      provideHover(model, position) {
        const word = model.getWordAtPosition(position);
        const before = prefix(model, position);
        if (!word || matlabCode(before).inNonCode || /\.\w*$/.test(before)) return null;
        const local = localAt(model, word.word);
        if (local) return { contents: [{ value: `**${local.name}** — current-document lexical ${local.kind}, line ${local.line}.\n\nNo type or scope inference.`, isTrusted: false }] };
        const item = MATLAB_SYMBOLS.get(word.word);
        if (!item) return null;
        return { contents: [
          { value: `\`\`\`matlab\n${item.signatures.map(signature => signature.label).join('\n')}\n\`\`\``, isTrusted: false },
          { value: `${item.documentation}\n\n**Requires: ${item.product}**\n\nOffline catalog; installation and name resolution are not checked.`, isTrusted: false },
        ] };
      },
    }),
    monaco.languages.registerSignatureHelpProvider('matlab', {
      signatureHelpTriggerCharacters: ['(', ','], signatureHelpRetriggerCharacters: [')'],
      provideSignatureHelp(model, position) {
        const call = matlabCallContext(prefix(model, position));
        if (!call || localAt(model, call.name)) return null;
        const item = MATLAB_SYMBOLS.get(call.name);
        if (!item) return null;
        const selected = Math.max(0, item.signatures.findIndex(signature => signature.parameters.length > call.parameter));
        return { value: {
          signatures: item.signatures.map(signature => ({ label: signature.label,
            documentation: `${item.documentation} Requires: ${item.product}. Selected offline signatures only.`,
            parameters: signature.parameters.map(label => ({ label })),
          })),
          activeSignature: selected, activeParameter: Math.min(call.parameter, Math.max(0, item.signatures[selected].parameters.length - 1)),
        }, dispose() {} };
      },
    }),
  ];
  return { get cachedModels() { return cache.size; }, dispose() { disposables.forEach(item => item.dispose()); cache.dispose(); } };
}

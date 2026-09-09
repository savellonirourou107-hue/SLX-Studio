import * as monaco from 'monaco-editor/editor/editor.api.js';
import 'monaco-editor/editor/contrib/find/browser/findController.js';
import 'monaco-editor/editor/contrib/folding/browser/folding.js';
import 'monaco-editor/editor/contrib/bracketMatching/browser/bracketMatching.js';
import 'monaco-editor/editor/contrib/multicursor/browser/multicursor.js';
import 'monaco-editor/editor/contrib/contextmenu/browser/contextmenu.js';
import 'monaco-editor/editor/contrib/hover/browser/hoverContribution.js';

window.MonacoEnvironment = { getWorker: () => new Worker(new URL('./editor.worker.js', window.location.href), { type: 'module' }) };
monaco.languages.register({ id: 'matlab', extensions: ['.m'] });
monaco.languages.setLanguageConfiguration('matlab', {
  comments: { lineComment: '%', blockComment: ['%{', '%}'] },
  brackets: [['(', ')'], ['[', ']'], ['{', '}']],
  autoClosingPairs: [{ open: '(', close: ')' }, { open: '[', close: ']' }, { open: '{', close: '}' }, { open: '"', close: '"' }],
});
// Syntax-only tokenizer. It intentionally does not claim MATLAB language-server semantics.
monaco.languages.setMonarchTokensProvider('matlab', {
  defaultToken: '',
  keywords: ['function', 'end', 'if', 'else', 'elseif', 'for', 'parfor', 'while', 'switch', 'case', 'otherwise', 'try', 'catch', 'return', 'break', 'continue', 'classdef', 'properties', 'methods', 'arguments', 'persistent', 'global'],
  tokenizer: { root: [
    [/%\{/, 'comment', '@comment'], [/%.*$/, 'comment'],
    [/"(?:[^"\n]|"")*"/, 'string'],
    [/'(?:[^'\n]|'')*'/, 'string'],
    [/[a-zA-Z_]\w*/, { cases: { '@keywords': 'keyword', '@default': 'identifier' } }],
    [/\d*\.?\d+(?:[eE][+-]?\d+)?[ij]?/, 'number'],
    [/[{}()[\]]/, '@brackets'], [/[-+*/\\^=<>~:;&|]+/, 'operator'],
  ], comment: [[/%\}/, 'comment', '@pop'], [/./, 'comment']] },
});
monaco.editor.defineTheme('slx-dark', {
  base: 'vs-dark', inherit: true,
  rules: [{ token: 'comment', foreground: '839B81' }, { token: 'keyword', foreground: '8CB6E2' }, { token: 'string', foreground: 'D8B68C' }, { token: 'number', foreground: 'B8A2D7' }],
  colors: { 'editor.background': '#151b22', 'editor.foreground': '#dbe3ea', 'editorLineNumber.foreground': '#50616e', 'editorCursor.foreground': '#86c5b8', 'editor.selectionBackground': '#335b6355', 'editor.lineHighlightBackground': '#1b242d' },
});
export { monaco };

/** Select a MATLAB %% section without treating block-comment contents as cells. */
export function matlabSection(source: string, lineNumber: number): { code: string; startLine: number; endLine: number } {
  const lines = source.split(/\r\n|\r|\n/);
  const caret = Math.max(1, Math.min(Math.floor(lineNumber), lines.length));
  const boundaries = [1];
  let blockComment = false;
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index].trim();
    if (line === '%{') { blockComment = true; continue; }
    if (line === '%}') { blockComment = false; continue; }
    if (!blockComment && /^%%/.test(line) && index > 0) boundaries.push(index + 1);
  }
  const startLine = boundaries.filter(line => line <= caret).at(-1)!;
  const endLine = (boundaries.find(line => line > caret) || lines.length + 1) - 1;
  return { code: lines.slice(startLine - 1, endLine).join('\n'), startLine, endLine };
}

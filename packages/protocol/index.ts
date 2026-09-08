export interface DocumentSnapshot {
  path: string;
  content: string;
  sha256: string;
  bom: boolean;
  eol: 'LF' | 'CRLF';
  mixed_eol: boolean;
  bytes: number;
  mtime_ns: number;
}
export interface DirectoryPage {
  path: string;
  items: { name: string; path: string; kind: 'directory' | 'm' | 'slx' }[];
  next_cursor: number | null;
  truncated: boolean;
}
export interface WorkspaceInfo {
  root: string;
  initial_file: string | null;
  protocol_version: number;
  capabilities: string[];
  matlab_started: boolean;
}
export interface Draft {
  path: string;
  content: string;
  base: DocumentSnapshot;
}
export type Result<T> = { ok: true; value: T } | { ok: false; error: string; kind: string };
export interface DesktopAPI {
  workspace(): Promise<Result<WorkspaceInfo | null>>;
  chooseWorkspace(): Promise<Result<WorkspaceInfo | null>>;
  listDirectory(path: string, cursor: number): Promise<Result<DirectoryPage>>;
  readDocument(path: string): Promise<Result<DocumentSnapshot>>;
  saveDocument(path: string, content: string, hash: string, bom: boolean): Promise<Result<DocumentSnapshot>>;
  loadDraft(path: string): Promise<Result<Draft | null>>;
  storeDraft(draft: Draft | { path: string; clear: true }): Promise<Result<null>>;
  onCommand(callback: (command: string) => void): () => void;
  onClose(callback: () => void): () => void;
  confirmClose(): void;
}
declare global { interface Window { slx: DesktopAPI; MonacoEnvironment: { getWorker: () => Worker }; } }

export function unwrap<T>(result: Result<T>): T {
  if (!result.ok) throw Object.assign(new Error(result.error), { kind: result.kind });
  return result.value;
}

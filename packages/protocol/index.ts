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
export interface ModelBlock { system_id: string; sid: string; name: string; block_type: string; path: string; parameters: Readonly<Record<string, string>>; }
export interface ModelLine { system_id: string; src: string; dst: string; name: string; }
export interface ModelInspectOptions { blockCursor?: number; lineCursor?: number; pageSize?: number; }
export interface ModelViewportOptions { systemId?: string; query?: string; cursor?: number; expectedSha256?: string; }
export interface ModelViewport {
  schema_version: string; name: string; sha256: string; metadata: Readonly<Record<string, unknown>>;
  systems: readonly { id: string; label: string; blocks: number }[];
  total_systems: number; systems_truncated: boolean; system_id: string;
  total_blocks: number; total_lines: number; system_blocks: number; system_lines: number;
  matched_blocks: number; cursor: number; next_cursor: number | null;
  blocks: readonly ModelBlock[]; lines: readonly ModelLine[]; omitted_lines: number;
}
export interface ModelDiffOptions { addedBlockCursor?: number; removedBlockCursor?: number; changedBlockCursor?: number; addedLineCursor?: number; removedLineCursor?: number; pageSize?: number; }
export interface ModelSnapshot { schema_version: string; name: string; metadata: Readonly<Record<string, unknown>>; blocks: readonly ModelBlock[]; lines: readonly ModelLine[]; total_blocks: number; total_lines: number; block_cursor: number; line_cursor: number; page_size: number; next_block_cursor: number | null; next_line_cursor: number | null; }
export interface ModelDiff { schema_version: string; old_name: string; new_name: string; changed: boolean; change_count: number; added_blocks: readonly ModelBlock[]; removed_blocks: readonly ModelBlock[]; changed_blocks: readonly { before: ModelBlock; after: ModelBlock; parameter_changes: readonly { name: string; before: string | null; after: string | null }[] }[]; added_lines: readonly ModelLine[]; removed_lines: readonly ModelLine[]; total_added_blocks: number; total_removed_blocks: number; total_changed_blocks: number; total_added_lines: number; total_removed_lines: number; page_size: number; next_added_block_cursor: number | null; next_removed_block_cursor: number | null; next_changed_block_cursor: number | null; next_added_line_cursor: number | null; next_removed_line_cursor: number | null; }
export type ConfigurationValue = boolean | number | string | null | readonly ConfigurationValue[] | { readonly [key: string]: ConfigurationValue };
export interface ConfigurationFile { scope: 'user' | 'workspace'; exists: boolean; sha256: string | null; values: Readonly<Record<string, ConfigurationValue>>; issues: readonly string[]; }
export interface ConfigurationState { effective: Readonly<Record<string, ConfigurationValue>>; user: ConfigurationFile; workspace: ConfigurationFile; }
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
  inspectModel(path: string, options?: ModelInspectOptions): Promise<Result<ModelSnapshot>>;
  modelViewport(path: string, options?: ModelViewportOptions): Promise<Result<ModelViewport>>;
  diffModels(oldPath: string, newPath: string, includeLayout: boolean, options?: ModelDiffOptions): Promise<Result<ModelDiff>>;
  configuration(): Promise<Result<ConfigurationState>>;
  updateConfiguration(scope: 'user' | 'workspace', values: Readonly<Record<string, ConfigurationValue>>, expectedSha256: string | null): Promise<Result<ConfigurationState>>;
  restartBackend(): Promise<Result<WorkspaceInfo>>;
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

import type { ConfigurationState, ConfigurationValue, DesktopAPI, DirectoryPage, DocumentSnapshot, Draft, ModelDiff, ModelSnapshot, WorkspaceInfo } from '../protocol';
import { unwrap } from '../protocol';

export interface FileService {
  list(path?: string, cursor?: number): Promise<DirectoryPage>;
  read(path: string): Promise<DocumentSnapshot>;
  save(base: DocumentSnapshot, content: string): Promise<DocumentSnapshot>;
}
export class DesktopServices implements FileService {
  constructor(private readonly api: DesktopAPI) {}
  async workspace(): Promise<WorkspaceInfo | null> { return unwrap(await this.api.workspace()); }
  async chooseWorkspace(): Promise<WorkspaceInfo | null> { return unwrap(await this.api.chooseWorkspace()); }
  async list(path = '', cursor = 0): Promise<DirectoryPage> { return unwrap(await this.api.listDirectory(path, cursor)); }
  async read(path: string): Promise<DocumentSnapshot> { return unwrap(await this.api.readDocument(path)); }
  async save(base: DocumentSnapshot, content: string): Promise<DocumentSnapshot> { return unwrap(await this.api.saveDocument(base.path, content, base.sha256, base.bom)); }
  async inspect(path: string): Promise<ModelSnapshot> { return unwrap(await this.api.inspectModel(path)); }
  async diff(oldPath: string, newPath: string, includeLayout = false): Promise<ModelDiff> { return unwrap(await this.api.diffModels(oldPath, newPath, includeLayout)); }
  async configuration(): Promise<ConfigurationState> { return unwrap(await this.api.configuration()); }
  async updateConfiguration(scope: 'user' | 'workspace', values: Readonly<Record<string, ConfigurationValue>>, expectedSha256: string | null): Promise<ConfigurationState> { return unwrap(await this.api.updateConfiguration(scope, values, expectedSha256)); }
  async restartBackend(): Promise<WorkspaceInfo> { return unwrap(await this.api.restartBackend()); }
  async draft(path: string): Promise<Draft | null> { return unwrap(await this.api.loadDraft(path)); }
  async keepDraft(draft: Draft): Promise<void> { unwrap(await this.api.storeDraft(draft)); }
  async clearDraft(path: string): Promise<void> { unwrap(await this.api.storeDraft({ path, clear: true })); }
}

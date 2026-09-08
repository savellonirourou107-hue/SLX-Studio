export type ConfigurationValue = boolean | number | string | null | readonly ConfigurationValue[] | { readonly [key: string]: ConfigurationValue };
export interface ConfigurationSchema<T extends ConfigurationValue = ConfigurationValue> {
  key: string;
  defaultValue: T;
  validate(value: unknown): value is T;
  workspaceWritable?: boolean;
  sensitive?: boolean;
}
type Entry = ConfigurationSchema & { defaultValue: ConfigurationValue };

function copy<T extends ConfigurationValue>(value: T): T {
  return structuredClone(value);
}

export class ConfigurationStore {
  private readonly schemas = new Map<string, Entry>();
  private readonly user = new Map<string, ConfigurationValue>();
  private readonly workspace = new Map<string, ConfigurationValue>();
  constructor(schemas: readonly ConfigurationSchema[]) { for (const schema of schemas) this.register(schema); }
  register<T extends ConfigurationValue>(schema: ConfigurationSchema<T>): () => void {
    if (!schema || typeof schema.key !== 'string' || !/^[a-z][a-zA-Z0-9]*(?:\.[a-zA-Z][a-zA-Z0-9]*)+$/.test(schema.key) || this.schemas.has(schema.key) || typeof schema.validate !== 'function' || !schema.validate(schema.defaultValue)) throw new Error(`Invalid or duplicate configuration: ${schema?.key}`);
    const entry = Object.freeze({ ...schema, defaultValue: copy(schema.defaultValue) });
    this.schemas.set(schema.key, entry);
    return () => { if (this.schemas.get(schema.key) === entry) { this.schemas.delete(schema.key); this.user.delete(schema.key); this.workspace.delete(schema.key); } };
  }
  private schema(key: string): Entry {
    const schema = this.schemas.get(key);
    if (!schema) throw new Error(`Unknown configuration: ${key}`);
    return schema;
  }
  private set(target: Map<string, ConfigurationValue>, key: string, value: unknown, scope: 'user' | 'workspace'): void {
    const schema = this.schema(key);
    if (scope === 'workspace' && (!schema.workspaceWritable || schema.sensitive)) throw new Error(`Configuration is not workspace-writable: ${key}`);
    if (!schema.validate(value)) throw new Error(`Invalid value for configuration: ${key}`);
    target.set(key, copy(value));
  }
  setUser(key: string, value: unknown): void { this.set(this.user, key, value, 'user'); }
  setWorkspace(key: string, value: unknown): void { this.set(this.workspace, key, value, 'workspace'); }
  clearUser(key: string): void { this.schema(key); this.user.delete(key); }
  clearWorkspace(key: string): void { this.schema(key); this.workspace.delete(key); }
  get<T extends ConfigurationValue>(key: string): T {
    const schema = this.schema(key);
    const value = this.workspace.has(key) ? this.workspace.get(key)! : this.user.has(key) ? this.user.get(key)! : schema.defaultValue;
    return copy(value) as T;
  }
  effective(): Readonly<Record<string, ConfigurationValue>> {
    const values: Record<string, ConfigurationValue> = {};
    for (const key of this.schemas.keys()) values[key] = this.get(key);
    return Object.freeze(values);
  }
}

import type { DesktopServices } from '../../../packages/core/services';
import type { ConfigurationState, ConfigurationValue } from '../../../packages/protocol';

/** A real settings contribution; persistence stays behind the typed service. */
export class SettingsController {
  private state: ConfigurationState | null = null;
  private busy = false;
  private readonly scope: HTMLSelectElement;
  private readonly fontSize: HTMLInputElement;
  private readonly minimap: HTMLInputElement;
  private readonly message: HTMLElement;
  private initial = { fontSize: 14, minimap: false };
  constructor(
    private readonly dialog: HTMLDialogElement,
    private readonly files: DesktopServices,
    private readonly apply: (state: ConfigurationState) => void,
    private readonly hasWorkspace: () => boolean,
    private readonly log: (message: string) => void,
  ) {
    this.scope = dialog.querySelector<HTMLSelectElement>('#settings-scope')!;
    this.fontSize = dialog.querySelector<HTMLInputElement>('#settings-font-size')!;
    this.minimap = dialog.querySelector<HTMLInputElement>('#settings-minimap')!;
    this.message = dialog.querySelector('#settings-message')!;
    this.scope.onchange = () => this.render();
    dialog.querySelector<HTMLButtonElement>('#settings-close')!.onclick = () => dialog.close();
    dialog.querySelector<HTMLButtonElement>('#settings-reload')!.onclick = () => void this.run(async () => { await this.reload(); this.render(); });
    dialog.querySelector<HTMLButtonElement>('#settings-save')!.onclick = () => void this.run(() => this.save());
    dialog.oncancel = event => { if (this.busy) event.preventDefault(); };
  }
  async reload(): Promise<ConfigurationState> {
    const state = await this.files.configuration();
    this.state = state;
    this.apply(state);
    for (const layer of [state.user, state.workspace]) if (layer.issues.length) this.log(`Settings (${layer.scope}): ${layer.issues.join('; ')}`);
    return state;
  }
  async show(): Promise<void> {
    await this.reload();
    this.scope.querySelector<HTMLOptionElement>('[value="workspace"]')!.disabled = !this.hasWorkspace();
    if (!this.hasWorkspace()) this.scope.value = 'user';
    this.render();
    if (!this.dialog.open) this.dialog.showModal();
  }
  private render(): void {
    if (!this.state) return;
    const scope = this.scope.value as 'user' | 'workspace';
    const values = scope === 'user' ? this.state.user.values : this.state.effective;
    this.initial = { fontSize: (values['editor.fontSize'] as number | undefined) ?? 14, minimap: (values['editor.minimap'] as boolean | undefined) ?? false };
    this.fontSize.value = String(this.initial.fontSize);
    this.minimap.checked = this.initial.minimap;
    this.message.textContent = this.state[scope].issues.join('\n') || (scope === 'workspace' ? 'Workspace settings override user settings. No code is executed.' : 'User settings apply unless a workspace overrides them.');
  }
  private async run(work: () => Promise<void>): Promise<void> {
    if (this.busy) return;
    this.busy = true;
    const controls = this.dialog.querySelectorAll<HTMLButtonElement | HTMLInputElement | HTMLSelectElement>('button,input,select');
    controls.forEach(control => { control.disabled = true; });
    try { await work(); }
    catch (error) { this.message.textContent = (error as Error).message; }
    finally { this.busy = false; controls.forEach(control => { control.disabled = false; }); }
  }
  private async save(): Promise<void> {
    if (!this.state) return;
    const fontSize = Number(this.fontSize.value);
    if (!Number.isInteger(fontSize) || fontSize < 10 || fontSize > 32) throw new Error('Font size must be an integer from 10 to 32.');
    const scope = this.scope.value as 'user' | 'workspace';
    const values: Record<string, ConfigurationValue> = {};
    if (fontSize !== this.initial.fontSize) values['editor.fontSize'] = fontSize;
    if (this.minimap.checked !== this.initial.minimap) values['editor.minimap'] = this.minimap.checked;
    if (!Object.keys(values).length) { this.dialog.close(); return; }
    this.state = await this.files.updateConfiguration(scope, values, this.state[scope].sha256);
    this.apply(this.state);
    this.log(`Settings saved (${scope}).`);
    this.dialog.close();
  }
}

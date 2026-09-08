import type { DesktopServices } from '../core/services';
import type { ModelBlock, ModelViewport } from '../protocol';
import { scene } from './geometry';
import type { Box, Scene } from './geometry';

const make = <K extends keyof HTMLElementTagNameMap>(tag: K, className = '', text = '') => {
  const node = document.createElement(tag); node.className = className; node.textContent = text; return node;
};
const svg = <K extends keyof SVGElementTagNameMap>(tag: K, attributes: Record<string, string | number> = {}, text = '') => {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  node.textContent = text; return node;
};
let nextViewId = 0;

/** A bounded, disposable view: it retains one model page, not an entire SLX graph. */
export class ModelView {
  readonly element = make('div', 'model-view');
  private readonly system = make('select');
  private readonly search = make('input');
  private readonly notice = make('div', 'model-notice');
  private readonly outline = make('div', 'model-outline-list');
  private readonly inspector = make('div', 'model-inspector');
  private readonly canvas = svg('svg', { class: 'model-canvas', tabindex: 0, role: 'group', 'aria-label': 'Static model canvas' });
  private readonly stats = make('span', 'model-stats');
  private readonly previous = make('button', '', 'Previous blocks');
  private readonly next = make('button', '', 'Next blocks');
  private readonly arrowId = `model-arrow-${++nextViewId}`;
  private data?: ModelViewport;
  private geometry?: Scene;
  private camera: Box = { x: 0, y: 0, width: 800, height: 500 };
  private selected = '';
  private systemId?: string;
  private version?: string;
  private cursor = 0;
  private history: number[] = [];
  private revision = 0;
  private disposed = false;
  private timer?: ReturnType<typeof setTimeout>;
  private resize: ResizeObserver;
  private drag?: { x: number; y: number; camera: Box };
  constructor(
    readonly path: string,
    private readonly files: Pick<DesktopServices, 'viewport'>,
    private readonly inspected: (path: string, data: ModelViewport) => void,
  ) {
    const toolbar = make('div', 'model-toolbar');
    const label = make('label', '', 'System ');
    this.system.setAttribute('aria-label', 'Model subsystem'); label.append(this.system);
    const readOnly = make('span', 'model-readonly', 'READ ONLY');
    const reload = make('button', '', 'Reload model'); reload.onclick = () => void this.reload();
    toolbar.append(label, readOnly, reload);
    this.notice.setAttribute('role', 'status');
    const body = make('div', 'model-body');
    const outline = make('aside', 'model-outline');
    this.search.placeholder = 'Find blocks…'; this.search.maxLength = 200;
    this.search.setAttribute('aria-label', 'Find model blocks');
    outline.append(make('h3', '', 'BLOCKS'), this.search, this.outline);
    const viewport = make('div', 'model-viewport');
    const navigation = make('div', 'model-navigation');
    const fit = make('button', '', 'Fit'), minus = make('button', '', '−'), plus = make('button', '', '+');
    fit.setAttribute('aria-label', 'Fit model'); minus.setAttribute('aria-label', 'Zoom out'); plus.setAttribute('aria-label', 'Zoom in');
    fit.onclick = () => this.fit(); minus.onclick = () => this.zoom(1.25); plus.onclick = () => this.zoom(.8);
    navigation.append(minus, fit, plus); viewport.append(this.canvas, navigation);
    this.inspector.setAttribute('aria-label', 'Block inspector');
    body.append(outline, viewport, this.inspector);
    const footer = make('div', 'model-footer'); footer.append(this.stats, this.previous, this.next);
    this.element.append(toolbar, this.notice, body, footer);
    this.system.onchange = () => { this.systemId = this.system.value; this.resetPage(); void this.load(); };
    this.search.oninput = () => {
      clearTimeout(this.timer); ++this.revision;
      this.timer = setTimeout(() => { this.resetPage(); void this.load(); }, 200);
    };
    this.previous.onclick = () => { this.cursor = this.history.pop() ?? 0; void this.load(); };
    this.next.onclick = () => {
      if (this.data?.next_cursor != null) { this.history.push(this.cursor); this.cursor = this.data.next_cursor; void this.load(); }
    };
    this.canvas.onwheel = event => { event.preventDefault(); this.zoom(event.deltaY < 0 ? .9 : 1.1); };
    this.canvas.onpointerdown = event => {
      if (event.button !== 0 || (event.target as Element).closest('[data-block]')) return;
      this.drag = { x: event.clientX, y: event.clientY, camera: { ...this.camera } };
      this.canvas.setPointerCapture(event.pointerId);
    };
    this.canvas.onpointermove = event => {
      if (!this.drag) return;
      const rect = this.canvas.getBoundingClientRect();
      this.camera.x = this.drag.camera.x - (event.clientX - this.drag.x) * this.camera.width / Math.max(1, rect.width);
      this.camera.y = this.drag.camera.y - (event.clientY - this.drag.y) * this.camera.height / Math.max(1, rect.height);
      this.updateCamera();
    };
    this.canvas.onpointerup = this.canvas.onpointercancel = () => { this.drag = undefined; };
    this.canvas.onkeydown = event => {
      if ((event.target as Element).closest('[data-block]')) return;
      if (event.key === 'Home') this.fit();
      else if (event.key === '+' || event.key === '=') this.zoom(.8);
      else if (event.key === '-') this.zoom(1.25);
      else if (event.key.startsWith('Arrow')) {
        this.camera.x += event.key === 'ArrowRight' ? this.camera.width / 10 : event.key === 'ArrowLeft' ? -this.camera.width / 10 : 0;
        this.camera.y += event.key === 'ArrowDown' ? this.camera.height / 10 : event.key === 'ArrowUp' ? -this.camera.height / 10 : 0;
        this.updateCamera();
      } else return;
      event.preventDefault();
    };
    this.resize = new ResizeObserver(() => { if (!this.element.hidden && this.geometry) this.updateCamera(); });
    this.resize.observe(this.canvas);
  }
  snapshot(): ModelViewport | undefined { return this.data; }
  private resetPage(): void { this.cursor = 0; this.history = []; }
  async reload(): Promise<void> {
    clearTimeout(this.timer); this.version = undefined; this.systemId = undefined; this.resetPage(); await this.load();
  }
  async load(): Promise<void> {
    const revision = ++this.revision;
    this.element.dataset.loading = 'true';
    this.next.disabled = this.previous.disabled = true;
    this.canvas.replaceChildren(); this.outline.replaceChildren(); this.inspector.replaceChildren();
    this.notice.textContent = 'Loading a bounded static page… MATLAB is not started.';
    try {
      const data = await this.files.viewport(this.path, { systemId: this.systemId, query: this.search.value, cursor: this.cursor, expectedSha256: this.version });
      if (this.disposed || revision !== this.revision) return;
      this.version = data.sha256; this.systemId = data.system_id; this.data = data;
      this.system.replaceChildren(...data.systems.map(system => {
        const option = make('option', '', `${system.label} (${system.blocks})`); option.value = system.id; return option;
      }));
      this.system.value = data.system_id;
      this.render(data); this.inspected(this.path, data);
      this.element.dataset.loading = 'false';
    } catch (error) {
      if (this.disposed || revision !== this.revision) return;
      this.data = undefined; this.geometry = undefined;
      this.element.dataset.loading = 'false';
      this.notice.textContent = `${(error as Error).message} Use Reload model to retry.`;
      this.stats.textContent = 'No model data displayed';
    }
  }
  private render(data: ModelViewport): void {
    this.geometry = scene(data.blocks, data.lines); this.selected = '';
    const fallback = this.geometry.nodes.filter(node => node.fallback).length;
    const warnings = Array.isArray(data.metadata.unsupported_features) ? data.metadata.unsupported_features.filter(item => typeof item === 'string').join(', ') : '';
    this.notice.textContent = `Static preview · approximate wires; no callbacks or simulation.${fallback ? ` ${fallback} blocks use fallback positions.` : ''}${data.omitted_lines ? ` ${data.omitted_lines} off-page or excess connections omitted.` : ''}${this.geometry.unresolved ? ` ${this.geometry.unresolved} unresolved connections.` : ''}${data.systems_truncated ? ` System list limited to ${data.systems.length}/${data.total_systems}.` : ''}${warnings ? ` Review warnings: ${warnings}.` : ''}`;
    this.stats.textContent = `${data.blocks.length ? data.cursor + 1 : 0}–${data.cursor + data.blocks.length} / ${data.matched_blocks} matching blocks · ${data.total_blocks} total · ${data.lines.length}/${data.system_lines} connections`;
    this.previous.disabled = this.history.length === 0; this.next.disabled = data.next_cursor === null;
    const defs = svg('defs'), marker = svg('marker', { id: this.arrowId, viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 6, markerHeight: 6, orient: 'auto-start-reverse' });
    marker.append(svg('path', { d: 'M 0 0 L 10 5 L 0 10 z', fill: '#8299aa' })); defs.append(marker);
    const wires = svg('g', { class: 'model-wires' });
    for (const wire of this.geometry.wires) {
      const path = svg('path', { d: wire.path, 'marker-end': `url(#${this.arrowId})`, class: 'model-wire' });
      path.dataset.source = wire.source; path.dataset.target = wire.target;
      path.append(svg('title', {}, `${wire.line.src} → ${wire.line.dst}${wire.line.name ? ` (${wire.line.name})` : ''}`));
      wires.append(path);
    }
    const blocks = svg('g', { class: 'model-blocks' });
    for (const { block, box, fallback: placed } of this.geometry.nodes) {
      const group = svg('g', { class: `model-block${placed ? ' fallback' : ''}`, transform: `translate(${box.x} ${box.y})`, tabindex: 0, role: 'button', 'aria-label': `Block ${block.name} (${block.block_type})`, 'aria-pressed': 'false' });
      group.dataset.block = block.path;
      group.append(svg('rect', { width: box.width, height: box.height, rx: 4 }));
      const symbol: Record<string, string> = { Gain: '×', Sum: 'Σ', Integrator: '∫', Inport: '→', Outport: '→', SubSystem: '▣', Constant: 'C' };
      group.append(svg('text', { x: box.width / 2, y: box.height / 2 + 5, class: 'model-symbol' }, symbol[block.block_type] || block.block_type.slice(0, 6)));
      group.append(svg('text', { x: box.width / 2, y: box.height + 18, class: 'model-label' }, block.name.length > 28 ? `${block.name.slice(0, 27)}…` : block.name));
      group.append(svg('title', {}, `${block.path}\n${block.block_type}\nSID ${block.sid}`));
      group.onclick = () => this.select(block);
      group.onkeydown = event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); this.select(block); } };
      blocks.append(group);
      const row = make('button', 'model-outline-row', block.name);
      row.title = `${block.path} · ${block.block_type}`; row.dataset.block = block.path;
      row.setAttribute('aria-label', `Inspect ${block.path}`); row.setAttribute('aria-pressed', 'false');
      row.onclick = () => { this.select(block); this.focusBlock(box); };
      this.outline.append(row);
    }
    this.canvas.replaceChildren(defs, wires, blocks);
    if (!data.blocks.length) this.outline.append(make('p', 'model-empty', 'No matching blocks.'));
    this.inspector.append(make('h3', '', 'INSPECTOR'), make('p', 'model-empty', 'Select a block to inspect its stored parameters.'));
    this.fit();
  }
  private select(block: ModelBlock): void {
    this.selected = block.path;
    for (const node of this.element.querySelectorAll<HTMLElement>('[data-block]')) {
      const selected = node.dataset.block === this.selected; node.classList.toggle('selected', selected); node.setAttribute('aria-pressed', String(selected));
    }
    for (const wire of this.element.querySelectorAll<SVGPathElement>('.model-wire')) wire.classList.toggle('selected', wire.dataset.source === this.selected || wire.dataset.target === this.selected);
    this.inspector.replaceChildren(make('h3', '', 'INSPECTOR'), make('h4', '', block.name), make('p', 'model-block-path', block.path));
    const details = make('dl');
    const entries = [['Type', block.block_type], ['SID', block.sid], ...Object.entries(block.parameters)];
    for (const [key, value] of entries.slice(0, 102)) details.append(make('dt', '', key), make('dd', '', value.length > 4096 ? `${value.slice(0, 4096)}… [truncated]` : value));
    this.inspector.append(details, make('p', 'model-empty', 'Stored text only; parameter expressions are not evaluated.'));
    if (entries.length > 102) this.inspector.append(make('p', 'model-empty', 'Parameter list limited to 100 entries.'));
  }
  private focusBlock(box: Box): void {
    this.camera.x = box.x + box.width / 2 - this.camera.width / 2;
    this.camera.y = box.y + box.height / 2 - this.camera.height / 2; this.updateCamera();
  }
  private updateCamera(): void { this.canvas.setAttribute('viewBox', `${this.camera.x} ${this.camera.y} ${this.camera.width} ${this.camera.height}`); }
  private fit(): void {
    if (!this.geometry) return;
    const box = this.geometry.bounds, rect = this.canvas.getBoundingClientRect();
    const ratio = Math.max(1, rect.width) / Math.max(1, rect.height);
    const width = Math.max(box.width, box.height * ratio), height = Math.max(box.height, box.width / ratio);
    this.camera = { x: box.x - (width - box.width) / 2, y: box.y - (height - box.height) / 2, width, height }; this.updateCamera();
  }
  private zoom(factor: number): void {
    const width = this.camera.width * factor;
    if (width < 40 || width > 10_000_000) return;
    this.camera.x += (this.camera.width - width) / 2;
    this.camera.y += (this.camera.height - this.camera.height * factor) / 2;
    this.camera.width = width; this.camera.height *= factor; this.updateCamera();
  }
  dispose(): void {
    this.disposed = true; ++this.revision; clearTimeout(this.timer); this.resize.disconnect();
    this.data = undefined; this.geometry = undefined; this.element.replaceChildren(); this.element.remove();
  }
}

export class ModelEditors {
  readonly documents = new Map<string, ModelView>();
  active: ModelView | null = null;
  constructor(private readonly container: HTMLElement, private readonly files: DesktopServices, private readonly changed: () => void, private readonly inspected: (path: string, data: ModelViewport) => void) {}
  async open(path: string): Promise<void> {
    if (this.documents.has(path)) { this.select(path); return; }
    if (this.documents.size >= 8) throw new Error('Close a model tab before opening more (8-tab preview limit).');
    const view = new ModelView(path, this.files, this.inspected);
    this.documents.set(path, view); this.container.append(view.element); this.select(path);
    await view.load();
  }
  select(path: string): void {
    const view = this.documents.get(path); if (!view) return;
    this.active = view;
    for (const candidate of this.documents.values()) candidate.element.hidden = candidate !== view;
    const snapshot = view.snapshot(); if (snapshot) this.inspected(path, snapshot);
    this.changed();
  }
  async reload(path: string): Promise<void> {
    const view = this.documents.get(path);
    if (view) await view.reload();
  }
  close(path: string): void {
    const view = this.documents.get(path); if (!view) return;
    view.dispose(); this.documents.delete(path);
    if (view === this.active) { this.active = null; const next = this.documents.keys().next().value; if (next) this.select(next); }
    this.changed();
  }
  closeAll(): void { for (const path of [...this.documents.keys()]) this.close(path); }
}

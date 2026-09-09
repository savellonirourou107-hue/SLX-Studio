import type { ModelBlock, ModelLine } from '../protocol';

export interface Box { x: number; y: number; width: number; height: number; }
export interface SceneNode { block: ModelBlock; box: Box; fallback: boolean; }
export interface SceneWire { line: ModelLine; path: string; source: string; target: string; }
export interface Scene { nodes: SceneNode[]; wires: SceneWire[]; bounds: Box; unresolved: number; }

export function position(raw: string | undefined): Box | null {
  if (!raw || raw.length > 200 || !/^\s*\[[\d+\-.,eE\s]+\]\s*$/.test(raw)) return null;
  const values = raw.trim().slice(1, -1).trim().split(/[\s,]+/).map(Number);
  if (values.length !== 4 || values.some(value => !Number.isFinite(value) || Math.abs(value) > 1_000_000)) return null;
  const [x, y, right, bottom] = values;
  const width = right - x, height = bottom - y;
  return width > 0 && height > 0 && width <= 10_000 && height <= 10_000 ? { x, y, width, height } : null;
}

export function endpoint(raw: string): { path: string; kind: string; port: number } | null {
  const match = /^(.*):(in|out)(\d+)$/.exec(raw);
  if (!match || !match[1] || Number(match[3]) < 1) return null;
  return { path: match[1], kind: match[2], port: Math.min(64, Number(match[3])) };
}

/** Layout facts only; wire curves approximate topology, never MATLAB routing. */
export function scene(blocks: readonly ModelBlock[], lines: readonly ModelLine[]): Scene {
  if (blocks.length > 160 || lines.length > 512) throw new Error('Viewport exceeds rendering limits');
  const supplied = blocks.map(block => position(block.parameters.Position));
  const fallbackX = supplied.reduce((right, box) => box ? Math.max(right, box.x + box.width + 120) : right, 40);
  let missing = 0;
  const nodes = blocks.map((block, index) => {
    const saved = supplied[index];
    const box = saved || { x: fallbackX + (missing % 4) * 180, y: 60 + Math.floor(missing / 4) * 110, width: 100, height: 44 };
    if (!saved) missing++;
    return { block, box, fallback: !saved };
  });
  const byPath = new Map(nodes.map(node => [node.block.path, node]));
  const ports = new Map<string, number>();
  for (const line of lines) for (const raw of [line.src, line.dst]) {
    const point = endpoint(raw);
    if (point) ports.set(`${point.path}\0${point.kind}`, Math.max(point.port, ports.get(`${point.path}\0${point.kind}`) || 0));
  }
  const wires: SceneWire[] = [];
  let unresolved = 0;
  for (const line of lines) {
    const source = endpoint(line.src), target = endpoint(line.dst);
    const from = source && byPath.get(source.path), to = target && byPath.get(target.path);
    if (!source || !target || !from || !to || source.kind !== 'out' || target.kind !== 'in') { unresolved++; continue; }
    const ax = from.box.x + from.box.width, bx = to.box.x;
    const ay = from.box.y + from.box.height * source.port / ((ports.get(`${source.path}\0out`) || 1) + 1);
    const by = to.box.y + to.box.height * target.port / ((ports.get(`${target.path}\0in`) || 1) + 1);
    const bend = Math.max(35, Math.abs(bx - ax) * .45);
    wires.push({ line, source: source.path, target: target.path, path: `M ${ax} ${ay} C ${ax + bend} ${ay}, ${bx - bend} ${by}, ${bx} ${by}` });
  }
  const left = Math.min(0, ...nodes.map(node => node.box.x - 40));
  const top = Math.min(0, ...nodes.map(node => node.box.y - 40));
  const right = Math.max(400, ...nodes.map(node => node.box.x + node.box.width + 80));
  const bottom = Math.max(240, ...nodes.map(node => node.box.y + node.box.height + 65));
  return { nodes, wires, bounds: { x: left, y: top, width: right - left, height: bottom - top }, unresolved };
}

import type { ModelJobStatus } from '../protocol';

const node = (tag: string, text = '') => Object.assign(document.createElement(tag), { textContent: text });
const svg = (tag: string, attributes: Record<string, string | number>, text = '') => {
  const element = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, String(value));
  element.textContent = text; return element;
};

/** Data-only result renderer, bounded to one signal, no webview or HTML from MATLAB. */
export function showModelJob(target: HTMLElement, job: ModelJobStatus): void {
  target.dataset.jobId = job.id; target.dataset.state = job.state;
  target.replaceChildren(node('h3', `${job.kind} · ${job.state} · ${job.path}`), node('p', `Run ${job.id} · independent MATLAB batch session (not Command Window state)`),
    node('p', `Input SHA-256: ${job.source_sha256}`));
  if (job.saved_sha256) target.append(node('p', `Saved SHA-256: ${job.saved_sha256}`));
  if (job.error || job.result?.message) target.append(node('p', job.error || job.result?.message));
  const simulation = job.result?.simulation;
  if (!simulation?.ran) return;
  target.append(node('p', `MATLAB ${simulation.matlab_release} · solver ${simulation.solver} (${simulation.solver_type}) · StopTime ${simulation.stop_time} · ${simulation.elapsed_seconds.toFixed(3)} s`),
    node('p', 'Preview limits: 12 scalar time series, 1500 finite samples per series; longer signals are sampled. This is not the full simulation dataset.'));
  const series = Array.isArray(simulation.series) ? simulation.series.slice(0, 12) : simulation.series ? [simulation.series] : [];
  if (!series.length) { target.append(node('p', 'No supported time series exported. Enable model output/signal logging or a To Workspace timeseries.')); return; }
  const select = document.createElement('select'); select.setAttribute('aria-label', 'Simulation signal');
  select.replaceChildren(...series.map((item, index) => Object.assign(document.createElement('option'), { value: String(index), textContent: item.name })));
  const plot = svg('svg', { viewBox: '0 0 800 240', role: 'img', 'aria-label': 'Simulation signal plot', class: 'simulation-plot' });
  const draw = () => {
    const item = series[Number(select.value)];
    const times = Array.isArray(item?.time) ? item.time : [item?.time];
    const values = Array.isArray(item?.data) ? item.data : [item?.data];
    const points = times.slice(0, 1500).map((time, index) => [time, values[index]]).filter(pair => pair.every(Number.isFinite));
    if (!points.length) { plot.replaceChildren(); return; }
    const x0 = Math.min(...points.map(pair => pair[0])), x1 = Math.max(...points.map(pair => pair[0]));
    const y0 = Math.min(...points.map(pair => pair[1])), y1 = Math.max(...points.map(pair => pair[1]));
    const coordinates = points.map(([x, y]) => `${50 + (x - x0) / (x1 - x0 || 1) * 720},${y1 === y0 ? 110 : 190 - (y - y0) / (y1 - y0) * 160}`).join(' ');
    plot.replaceChildren(svg('path', { d: 'M50 25V190H775', stroke: '#748ba0', fill: 'none' }),
      svg('polyline', { points: coordinates, stroke: '#77d1c5', 'stroke-width': 2, fill: 'none' }),
      svg('text', { x: 50, y: 220 }, `${x0.toPrecision(4)} → ${x1.toPrecision(4)} s · ${item.name} · ${points.length} displayed samples`),
      svg('text', { x: 50, y: 18 }, `value range ${y0.toPrecision(4)} → ${y1.toPrecision(4)}`));
  };
  select.onchange = draw; target.append(select, plot); draw();
}

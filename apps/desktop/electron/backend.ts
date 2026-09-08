import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { EventEmitter } from 'node:events';
const MAX_FRAME = 16 * 1024 * 1024;

export class FrameDecoder {
  private buffer = Buffer.alloc(0);
  private length: number | null = null;
  feed(chunk: Buffer): unknown[] {
    if (this.buffer.length + chunk.length > MAX_FRAME * 2 + 4096) throw new Error('Backend buffer exceeded');
    this.buffer = Buffer.concat([this.buffer, chunk]);
    const messages: unknown[] = [];
    while (true) {
      if (this.length === null) {
        const boundary = this.buffer.indexOf('\r\n\r\n');
        if (boundary < 0) {
          if (this.buffer.length > 4096) throw new Error('Oversized backend header');
          break;
        }
        if (boundary > 4096) throw new Error('Oversized backend header');
        const header = this.buffer.subarray(0, boundary).toString('ascii');
        const lengths = header.split('\r\n').filter(line => /^content-length:/i.test(line));
        if (lengths.length !== 1 || !/^content-length: *\d+$/i.test(lengths[0])) throw new Error('Invalid backend framing');
        this.length = Number(lengths[0].split(':')[1]);
        if (!Number.isSafeInteger(this.length) || this.length < 1 || this.length > MAX_FRAME) throw new Error('Backend frame exceeds limit');
        this.buffer = this.buffer.subarray(boundary + 4);
      }
      if (this.buffer.length < this.length) break;
      const raw = new TextDecoder('utf-8', { fatal: true }).decode(this.buffer.subarray(0, this.length));
      this.buffer = this.buffer.subarray(this.length);
      this.length = null;
      messages.push(JSON.parse(raw));
    }
    return messages;
  }
}

export class PythonBackend extends EventEmitter {
  private readonly child: ChildProcessWithoutNullStreams;
  private readonly pending = new Map<number, { resolve: (value: any) => void; reject: (error: Error) => void; timer: NodeJS.Timeout }>();
  private id = 0;
  private closed = false;
  constructor(python: string, workspace: string, sourceRoot: string, state: string) {
    super();
    this.child = spawn(python, ['-u', '-m', 'slxdiff.rpc', '--workspace', workspace], {
      cwd: sourceRoot, windowsHide: true, shell: false,
      env: { ...process.env, PYTHONPATH: `${sourceRoot}/src`, PYTHONDONTWRITEBYTECODE: '1', SLX_STUDIO_STATE_DIR: state },
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    const decoder = new FrameDecoder();
    this.child.stdout.on('data', (data: Buffer) => {
      try {
        for (const value of decoder.feed(data)) {
          const message = value as { jsonrpc?: string; id?: number; result?: unknown; error?: { message: string; data?: { kind?: string } } };
          if (!message || message.jsonrpc !== '2.0' || typeof message.id !== 'number' || !this.pending.has(message.id)) throw new Error('Unexpected backend response');
          const request = this.pending.get(message.id)!;
          this.pending.delete(message.id);
          clearTimeout(request.timer);
          if (message.error) request.reject(Object.assign(new Error(message.error.message), { kind: message.error.data?.kind }));
          else request.resolve(message.result);
        }
      } catch (error) { this.fail(error as Error); }
    });
    // Drain continuously; never concatenate unbounded process output in memory.
    this.child.stderr.on('data', (data: Buffer) => this.emit('diagnostic', data.subarray(0, 4096).toString('utf8')));
    this.child.on('error', error => this.fail(error));
    this.child.on('exit', () => this.fail(new Error('Python backend exited; use Backend: Restart Python Service.')));
    this.child.stdin.on('error', error => this.fail(error));
  }
  request<T>(method: string, params: object = {}): Promise<T> {
    if (this.closed) return Promise.reject(new Error('Python backend is closed; requests are never replayed.'));
    if (this.pending.size >= 32) return Promise.reject(new Error('Too many pending backend requests'));
    const id = ++this.id;
    const payload = Buffer.from(JSON.stringify({ jsonrpc: '2.0', id, method, params }), 'utf8');
    if (payload.length > MAX_FRAME) return Promise.reject(new Error('Request exceeds the frame size limit'));
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => this.fail(new Error('Python request timed out; not replayed.')), 30_000);
      this.pending.set(id, { resolve, reject, timer });
      this.child.stdin.write(Buffer.concat([Buffer.from(`Content-Length: ${payload.length}\r\n\r\n`), payload]));
    });
  }
  private fail(error: Error): void {
    if (this.closed) return;
    this.closed = true;
    for (const pending of this.pending.values()) { clearTimeout(pending.timer); pending.reject(error); }
    this.pending.clear();
    this.child.stdin.end();
    if (this.child.exitCode === null) this.child.kill();
  }
  close(): void { this.fail(new Error('Backend closed by the desktop')); }
}

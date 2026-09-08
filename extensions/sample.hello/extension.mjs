export function activate() {
  return {
    commands: [{ command: 'sample.hello', title: 'Sample: Hello SLX Studio' }],
    views: [{ id: 'sample.hello.view', title: 'Sample Inspector', location: 'sidebar' }],
    editors: [{ id: 'sample.hello.editor', label: 'Sample Preview', extensions: ['.slxpreview'] }],
  };
}

export function execute(command, args = {}) {
  if (command !== 'sample.hello') throw new Error(`Unknown sample command: ${command}`);
  return { message: 'Hello from the trusted SLX Studio extension host.', args };
}

export function deactivate() {}

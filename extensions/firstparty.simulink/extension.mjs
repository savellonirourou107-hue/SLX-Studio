// Privileged Simulink access stays in the typed renderer/preload API.
export function activate() { return {}; }
export function execute(command) { return { action: command, transport: 'typed-model-service' }; }
export function deactivate() {}

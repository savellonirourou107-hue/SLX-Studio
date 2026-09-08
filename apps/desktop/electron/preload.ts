import { contextBridge, ipcRenderer } from 'electron';
import type { DesktopAPI, Draft } from '../../../packages/protocol';

const subscribe = (channel: string, callback: (...args: any[]) => void): (() => void) => {
  const listener = (_event: unknown, ...values: unknown[]) => callback(...values);
  ipcRenderer.on(channel, listener);
  return () => ipcRenderer.removeListener(channel, listener);
};
const api: DesktopAPI = {
  workspace: () => ipcRenderer.invoke('slx:workspace'),
  chooseWorkspace: () => ipcRenderer.invoke('slx:chooseWorkspace'),
  listDirectory: (path, cursor) => ipcRenderer.invoke('slx:list', { path, cursor }),
  readDocument: path => ipcRenderer.invoke('slx:read', { path }),
  saveDocument: (path, content, hash, bom) => ipcRenderer.invoke('slx:save', { path, content, hash, bom }),
  inspectModel: (path, options = {}) => ipcRenderer.invoke('slx:inspect', { path, ...options }),
  diffModels: (oldPath, newPath, includeLayout, options = {}) => ipcRenderer.invoke('slx:diff', { oldPath, newPath, includeLayout, ...options }),
  configuration: () => ipcRenderer.invoke('slx:configuration'),
  updateConfiguration: (scope, values, expectedSha256) => ipcRenderer.invoke('slx:updateConfiguration', { scope, values, expectedSha256 }),
  restartBackend: () => ipcRenderer.invoke('slx:restartBackend'),
  loadDraft: path => ipcRenderer.invoke('slx:loadDraft', { path }),
  storeDraft: (draft: Draft | { path: string; clear: true }) => ipcRenderer.invoke('slx:storeDraft', draft),
  onCommand: callback => subscribe('slx:command', callback),
  onClose: callback => subscribe('slx:closeRequested', callback),
  confirmClose: () => ipcRenderer.send('slx:closeConfirmed'),
};
contextBridge.exposeInMainWorld('slx', api);

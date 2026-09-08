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
  modelViewport: (path, options = {}) => ipcRenderer.invoke('slx:viewport', { ...options, path }),
  diffModels: (oldPath, newPath, includeLayout, options = {}) => ipcRenderer.invoke('slx:diff', { oldPath, newPath, includeLayout, ...options }),
  applyModelEdit: (path, edit, outputPath) => ipcRenderer.invoke('slx:modelApplyEdit', { path, edit, outputPath }),
  configuration: () => ipcRenderer.invoke('slx:configuration'),
  updateConfiguration: (scope, values, expectedSha256) => ipcRenderer.invoke('slx:updateConfiguration', { scope, values, expectedSha256 }),
  restartBackend: () => ipcRenderer.invoke('slx:restartBackend'),
  loadDraft: path => ipcRenderer.invoke('slx:loadDraft', { path }),
  storeDraft: (draft: Draft | { path: string; clear: true }) => ipcRenderer.invoke('slx:storeDraft', draft),
  matlabStatus: () => ipcRenderer.invoke('slx:matlabStatus'),
  matlabStartCommand: command => ipcRenderer.invoke('slx:matlabCommandStart', { command }),
  matlabCommandStatus: (jobId, stdoutOffset = 0, stderrOffset = 0) => ipcRenderer.invoke('slx:matlabCommandStatus', { jobId, stdoutOffset, stderrOffset }),
  matlabStopCommand: jobId => ipcRenderer.invoke('slx:matlabCommandStop', { jobId }),
  matlabStartRun: (path, options = {}) => ipcRenderer.invoke('slx:matlabRunStart', { path, ...options }),
  matlabRunStatus: (jobId, stdoutOffset = 0, stderrOffset = 0) => ipcRenderer.invoke('slx:matlabRunStatus', { jobId, stdoutOffset, stderrOffset }),
  matlabStopRun: jobId => ipcRenderer.invoke('slx:matlabRunStop', { jobId }),
  extensionsList: () => ipcRenderer.invoke('slx:extensionsList'),
  extensionsActivate: id => ipcRenderer.invoke('slx:extensionsActivate', { id }),
  extensionsExecute: (id, command, args = {}) => ipcRenderer.invoke('slx:extensionsExecute', { id, command, args }),
  extensionsDeactivate: id => ipcRenderer.invoke('slx:extensionsDeactivate', { id }),
  onCommand: callback => subscribe('slx:command', callback),
  onClose: callback => subscribe('slx:closeRequested', callback),
  confirmClose: () => ipcRenderer.send('slx:closeConfirmed'),
};
contextBridge.exposeInMainWorld('slx', api);

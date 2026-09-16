% Isolated R2026a probe: run with pwd set to an empty acceptance directory.
% This deliberately exercises the same library add_block API as our bridge.
assert(strcmp(version('-release'), '2026a'), 'This probe freezes R2026a behavior.');
modelName = 'slxstudio_subsystem_defaults';
assert(~bdIsLoaded(modelName), 'Probe model name is already in use.');
new_system(modelName);
probeCleanup = onCleanup(@() close_system(modelName, 0));
load_system('simulink');
add_block('simulink/Ports & Subsystems/Subsystem', [modelName '/Probe']);
childPaths = find_system([modelName '/Probe'], 'SearchDepth', 1, 'Type', 'Block');
childPaths(strcmp(childPaths, [modelName '/Probe'])) = [];
childNames = get_param(childPaths, 'Name');
childTypes = get_param(childPaths, 'BlockType');
lineHandles = find_system([modelName '/Probe'], 'FindAll', 'on', 'SearchDepth', 1, 'Type', 'line');
report = struct('matlab_release', version('-release'), 'child_names', {childNames}, ...
    'child_types', {childTypes}, 'line_count', numel(lineHandles));
disp(jsonencode(report));
assert(isequal(sort(childNames), {'In1'; 'Out1'}), 'Library default children changed.');
assert(numel(lineHandles) == 1, 'Library default wiring changed.');
probeOutput = getenv('SLX_ACCEPTANCE_DIR');
assert(isfolder(probeOutput), 'Set SLX_ACCEPTANCE_DIR to an isolated output directory.');
save_system(modelName, fullfile(probeOutput, [modelName '.slx']));
clear probeCleanup;

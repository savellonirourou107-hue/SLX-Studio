function modelPath = make_live_demo(outputDir)
%MAKE_LIVE_DEMO Build a tiny simulation-ready model for SLX Studio v0.6.
% Requires MATLAB + Simulink.
%
% The model is intentionally simple:
%   Step -> Kp -> Limiter -> Output
%                     \-> Monitor (To Workspace)
%
% After generating it, try:
%   slx-diff studio slxdiff_live_demo.slx
% Then stage Kp/Gain from 2 to 3.5 and click Run Simulation.

if nargin == 0
    outputDir = pwd;
end
if ~isfolder(outputDir)
    mkdir(outputDir);
end

modelName = "slxdiff_live_demo";
modelPath = fullfile(outputDir, modelName + ".slx");
if bdIsLoaded(modelName)
    close_system(modelName, 0);
end

new_system(modelName);
set_param(modelName, "StopTime", "10");

add_block("simulink/Sources/Step", modelName + "/Reference", ...
    "Time", "1", "Before", "0", "After", "1", ...
    "Position", [30 105 60 135]);
add_block("simulink/Math Operations/Gain", modelName + "/Kp", ...
    "Gain", "2", "Position", [140 90 210 150]);
add_block("simulink/Discontinuities/Saturation", modelName + "/Limiter", ...
    "UpperLimit", "10", "LowerLimit", "-10", ...
    "Position", [300 90 390 150]);
add_block("simulink/Sinks/Out1", modelName + "/Output", ...
    "Position", [510 105 540 135]);
add_block("simulink/Sinks/To Workspace", modelName + "/Monitor", ...
    "VariableName", "monitor", "SaveFormat", "Timeseries", ...
    "Position", [500 210 590 250]);

add_line(modelName, "Reference/1", "Kp/1");
add_line(modelName, "Kp/1", "Limiter/1");
add_line(modelName, "Limiter/1", "Output/1");
add_line(modelName, "Limiter/1", "Monitor/1");

save_system(modelName, modelPath);
close_system(modelName, 0);
fprintf("Created simulation-ready demo:\n  %s\n", modelPath);
end

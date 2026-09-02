function make_demo_models(outputDir)
%MAKE_DEMO_MODELS Build two genuine Simulink models for the slx-diff demo.
% Requires MATLAB + Simulink. The generated files are intentionally tiny.

if nargin == 0
    outputDir = pwd;
end
if ~isfolder(outputDir)
    mkdir(outputDir);
end

before = fullfile(outputDir, "controller_before.slx");
after  = fullfile(outputDir, "controller_after.slx");

buildModel("slxdiff_before", 2, false, before);
buildModel("slxdiff_after",  3, true,  after);

fprintf("Created:\n  %s\n  %s\n", before, after);
end

function buildModel(modelName, gainValue, addScope, destination)
if bdIsLoaded(modelName)
    close_system(modelName, 0);
end
new_system(modelName);
add_block("simulink/Sources/In1", modelName + "/Input", Position=[30 90 60 110]);
add_block("simulink/Math Operations/Gain", modelName + "/Gain", ...
    Gain=string(gainValue), Position=[120 80 180 120]);
add_line(modelName, "Input/1", "Gain/1");

if addScope
    add_block("simulink/Sinks/Out1", modelName + "/Output", Position=[250 90 280 110]);
    add_line(modelName, "Gain/1", "Output/1");
end

save_system(modelName, destination);
close_system(modelName, 0);
end

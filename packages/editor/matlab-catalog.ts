/** Curated, offline hints. This is not toolbox discovery or MATLAB name resolution. */
export type MatlabProduct = 'MATLAB' | 'Simulink' | 'Control System Toolbox' | 'Simulink Control Design';
export interface MatlabSymbol {
  name: string;
  signatures: readonly { label: string; parameters: readonly string[] }[];
  documentation: string;
  product: MatlabProduct;
}

function symbol(name: string, product: MatlabProduct, documentation: string, ...forms: string[]): MatlabSymbol {
  return { name, product, documentation, signatures: forms.map(form => ({
    label: `${name}(${form})`, parameters: form ? form.split(',').map(parameter => parameter.trim()) : [],
  })) };
}

export const MATLAB_CATALOG: readonly MatlabSymbol[] = [
  symbol('zeros', 'MATLAB', 'Create an array of zeros.', 'n', 'rows, columns', 'sizeVector'),
  symbol('ones', 'MATLAB', 'Create an array of ones.', 'n', 'rows, columns'),
  symbol('eye', 'MATLAB', 'Create an identity matrix.', 'n', 'rows, columns'),
  symbol('linspace', 'MATLAB', 'Generate linearly spaced points.', 'x1, x2', 'x1, x2, n'),
  symbol('logspace', 'MATLAB', 'Generate logarithmically spaced points.', 'a, b', 'a, b, n'),
  symbol('size', 'MATLAB', 'Array dimensions.', 'A', 'A, dim'),
  symbol('length', 'MATLAB', 'Length of the largest array dimension.', 'A'),
  symbol('numel', 'MATLAB', 'Number of array elements.', 'A'),
  symbol('mean', 'MATLAB', 'Average along an array dimension.', 'A', 'A, dim'),
  symbol('sum', 'MATLAB', 'Sum along an array dimension.', 'A', 'A, dim'),
  symbol('max', 'MATLAB', 'Maximum array elements.', 'A', 'A, B'),
  symbol('min', 'MATLAB', 'Minimum array elements.', 'A', 'A, B'),
  symbol('sin', 'MATLAB', 'Sine of an angle in radians.', 'X'),
  symbol('cos', 'MATLAB', 'Cosine of an angle in radians.', 'X'),
  symbol('sqrt', 'MATLAB', 'Square root.', 'X'),
  symbol('disp', 'MATLAB', 'Display a value.', 'X'),
  symbol('fprintf', 'MATLAB', 'Write formatted text.', 'formatSpec, values', 'fileID, formatSpec, values'),
  symbol('plot', 'MATLAB', 'Create a 2-D line plot. Selected common signatures only.', 'X, Y', 'X, Y, LineSpec', 'ax, X, Y'),
  symbol('figure', 'MATLAB', 'Create or select a figure.', '', 'number'),
  symbol('xlabel', 'MATLAB', 'Label an x-axis.', 'text', 'ax, text'),
  symbol('ylabel', 'MATLAB', 'Label a y-axis.', 'text', 'ax, text'),
  symbol('title', 'MATLAB', 'Add a plot title.', 'text', 'ax, text'),
  symbol('legend', 'MATLAB', 'Add a plot legend.', 'labels'),
  symbol('sim', 'Simulink', 'Run a Simulink simulation explicitly; model code may execute.', 'modelName', 'simulationInput'),
  symbol('load_system', 'Simulink', 'Load a model into memory; model callbacks may execute.', 'modelName'),
  symbol('open_system', 'Simulink', 'Open a model or block.', 'system'),
  symbol('get_param', 'Simulink', 'Read a model or block parameter.', 'object, parameter'),
  symbol('set_param', 'Simulink', 'Set model or block parameters.', 'object, parameter, value'),
  symbol('add_block', 'Simulink', 'Add a library block to a model.', 'source, destination'),
  symbol('add_line', 'Simulink', 'Connect ports within one model or subsystem.', 'system, sourcePort, destinationPort'),
  symbol('tf', 'Control System Toolbox', 'Construct a transfer-function model.', 'numerator, denominator', 'numerator, denominator, sampleTime'),
  symbol('ss', 'Control System Toolbox', 'Construct a state-space model.', 'A, B, C, D', 'A, B, C, D, sampleTime'),
  symbol('step', 'Control System Toolbox', 'Step response of a dynamic system.', 'sys', 'sys, time'),
  symbol('bode', 'Control System Toolbox', 'Frequency-response magnitude and phase.', 'sys', 'sys, omega'),
  symbol('nyquist', 'Control System Toolbox', 'Nyquist frequency-response plot.', 'sys', 'sys, omega'),
  symbol('margin', 'Control System Toolbox', 'Gain and phase margins of a SISO loop transfer.', 'sys'),
  symbol('feedback', 'Control System Toolbox', 'Feedback interconnection, negative feedback by default.', 'sys1, sys2', 'sys1, sys2, sign'),
  symbol('pid', 'Control System Toolbox', 'Create a parallel-form PID controller; this does not tune it.', 'Kp, Ki, Kd', 'Kp, Ki, Kd, Tf'),
  symbol('linearize', 'Simulink Control Design', 'Linearize a model at explicitly selected I/O and operating point.', 'model, io', 'model, io, operatingPoint'),
];

export const MATLAB_SYMBOLS = new Map(MATLAB_CATALOG.map(item => [item.name, item]));

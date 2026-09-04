<div align="center">

# SLX Studio

### 面向 MATLAB `.m` 与 Simulink `.slx` 的轻量编辑 / 运行工作台

**写脚本、改模型、保存、运行；AI 和 Git 是辅助能力，不是主界面。**

[English](README.md) · [快速开始](#快速开始) · [m-文件编辑器](#m-文件编辑器) · [slx-图形编辑器](#slx-图形编辑器) · [桌面版](#桌面版与-exe) · [AI](#可选-ai-助手)

</div>

![SLX Studio v1.0 Beta](docs/assets/slx-studio-v10-beta.png)

> **状态：v1.0.0 Beta 2。** 现在是一个轻量 `.m + .slx` 工程 IDE：支持多标签编辑、按 `%%` 节运行、共享 Workspace 的 MATLAB Command Window、变量编辑、可停止的脚本/SLX 仿真/参数扫描 Job、MATLAB Figure、SimulationOutput 曲线、崩溃恢复草稿、工程搜索和 SLX 图形编辑。执行 `.m`、创建/修改/仿真真实 `.slx` 仍需要本机 MATLAB/Simulink。

## 产品定位

SLX Studio 不试图复制完整 MATLAB Desktop。它专门解决更轻量、频繁的工程循环：

```text
工程文件夹
├── controller.m   → 编辑 → 保存 → 运行 → Console + 变量
└── controller.slx → 图形编辑 → 保存 → 仿真
```

同一个工作区在代码与框图之间切换，AI / Git 工具保留，但不抢占主流程。

## 快速开始

```bash
pip install -e .
slx-studio .
```

也可以直接打开文件：

```bash
slx-studio controller.m
slx-studio controller.slx
```

MATLAB 不在 PATH 时：

```bash
slx-studio . --matlab "C:\\Program Files\\MATLAB\\R2026a\\bin\\matlab.exe"
```

也可以设置 `SLX_DIFF_MATLAB`。

原工程 CLI 继续保留：

```bash
slx-diff --version
slx-diff diff before.slx after.slx
```

## `.m` 文件编辑器

v1.0 Beta 的 `.m` 编辑器已经形成“编辑 → 运行 → 检查 → 再迭代”闭环：

- **多文件标签页**与未保存状态提示；
- 行号与轻量 MATLAB 语法高亮；
- Ctrl/Cmd+S 保存、Ctrl/Cmd+Shift+S 另存为、F5 运行整个文件；
- **Ctrl/Cmd+Enter 运行当前 `%%` Section 或选中代码**，报错行仍映射回原脚本；
- `.m` 使用真实后台 MATLAB Job，可通过 Stop 终止；
- 编辑器 Undo / Redo 与 MATLAB 报错行自动定位；
- stdout / stderr Console 与 **Workspace Variables**；
- MATLAB 风格 **Command Window (`>>`)**，通过临时会话 checkpoint 在多次后台运行之间继承变量；
- Workspace 变量可双击，用明确 MATLAB 表达式修改；
- 未保存 `.m` 会自动写入项目外的恢复草稿，异常退出后可恢复；
- MATLAB Figure 运行后直接回传并显示在 Plots 面板；
- Ctrl/Cmd+P Quick Open，以及 Ctrl/Cmd+Shift+F 同时搜索 `.m` 文本和静态 `.slx` Block/参数/信号。

```text
controller.m *        analysis.m
────────────────────────────────────
  1  clear; clc
  2  Kp = 2.5;
  3  t = 0:0.01:5;
  4  y = 1-exp(-Kp*t);

Console                       Workspace Variables
MATLAB run complete           Kp  2.5   double 1x1
                              t   …     double 1x501
                              y   …     double 1x501
```

![SLX Studio v1.0 Beta M 编辑器](docs/assets/slx-studio-v10-beta.png)

运行 `.m` 始终是用户主动操作。接入 DeepSeek/Kimi/OpenAI 等 API，不会自动把任意 MATLAB 代码执行权交给 AI。

## `.slx` 图形编辑器

![SLX Studio SLX 图形编辑器](docs/assets/slx-studio-v08-slx-editor.png)

没有 MATLAB 时可以轻量解析/查看 `.slx`；检测到本机 MATLAB/Simulink 后，同一画布进入真实编辑模式。

### v1.0 Beta 图形交互

- 点击 Block，在 Inspector 修改参数；
- **直接拖动 Block**，保存后真实 Simulink `Position` 同步变化；
- 拖动 Block 时信号线实时跟随；
- 根据已有连接显示明确的多输入/多输出端口，并支持**从指定输出端口拖到指定输入端口**创建 Connection；
- 可搜索 Block Palette；
- 新增、重命名、删除 Block；
- 删除信号连接；
- Save Model / Run Simulation；
- 结构修改和参数修改进入同一套 **SLX Undo / Redo**。

SLX 历史记录使用临时模型快照 + SHA-256 冲突检查。如果模型被外部 MATLAB 或其他程序改过，旧 Undo 会拒绝覆盖，而不是强行回滚外部修改。

### 为什么不直接改 SLX 内部 XML

真实写入仍交给 MATLAB/Simulink 标准程序化接口：

```text
set_param     add_block      delete_block
add_line      delete_line    save_system
sim
```

SLX Studio 负责轻量 UI、编辑意图和冲突保护；MATLAB 负责真实 `.slx` 序列化与执行。这样比浏览器自己伪造 SLX ZIP/XML 更可靠。

### 当前 Block Palette

首批安全目录包含 Inport、Outport、Step、Constant、Gain、Sum、Saturation、Integrator、Discrete-Time Integrator、Transfer Function、Unit Delay、Mux、Scope、To Workspace 等常用模块。后续通过 catalog 扩展，而不是把所有逻辑写死在前端。

## 运行、图形、扫参与工程导航

v1.0 Beta 加入了一组更像工程 IDE 的高频操作：

```text
Ctrl+Enter       运行当前 %% Section / 选中代码
F5               运行当前 .m
Shift+F5         停止当前 .m / SLX / Sweep MATLAB Job
Ctrl+Shift+P     Command Palette
Ctrl+P           Quick Open
Ctrl+Shift+F     搜索 .m 文本 + .slx Block/参数/信号
Ctrl+Shift+S     另存为
```

`.m` 执行结束后会捕获 MATLAB Figure 并显示在 Workbench。`.slx` 仿真则会从支持的数值 `timeseries` / `Simulink.SimulationData.Dataset` 中提取有界曲线数据，在本地 Plots 面板绘制。

### Command Window 与共享 Workspace

脚本、Section、Command Window 命令和变量编辑共享一个会话级 MATLAB Workspace checkpoint。SLX Studio **不会**把完整 MATLAB Desktop 常驻嵌进程序；每次用户主动运行时继承临时 checkpoint，并把新的用户变量写回。Workbench 关闭后，这个临时会话随之清理。

```text
运行 controller.m       → Kp = 2.5
Command: Kp = 3         → Kp = 3
双击变量把 Kp 改成 4    → Kp = 4
再运行下一节             → 能看到 Kp = 4
```

### Parameter Sweep 参数扫描

在 SLX 中选中模块后打开 **Sweep**，可以输入 `1:0.5:5`、`3:1` 或逗号列表。Studio 会后台执行多次仿真，结束后恢复原参数，不把扫描值偷偷保存到模型，并返回多曲线叠加和轻量指标。

```text
Controller/Kp · Gain
1 : 0.5 : 5
      ↓
9 次仿真
      ↓
多条响应曲线 + final / max / RMS / settling estimate
```

这些 Sweep 指标用于快速工程迭代，不等同于正式稳定性或安全验证。

## 新建文件

Workbench 顶部可以：

```text
新建 .m    → 新建并编辑 MATLAB 脚本
新建 .slx  → 调本机 MATLAB 创建真实空白 Simulink 模型
```

空白 `.slx` 可以手工搭建，也可以让可选 AI 先生成经过校验的 Blueprint，再由用户决定是否真正构建。

## 桌面版与 EXE

安装桌面依赖：

```bash
pip install -e ".[desktop]"
slx-studio
```

有 `pywebview` 时优先打开桌面 WebView，没有时可回退到浏览器。

仓库中的 `.github/workflows/build-windows.yml` 已配置为在版本 tag 上通过 `windows-latest` 同时构建便携版和安装版：

```text
SLXStudio.exe
SLX-Studio-Setup-x64.exe
```

安装器是当前用户级安装，并把桌面快捷方式、`.m` / `.slx` 文件关联设计成**用户主动勾选**，不会静默抢占文件关联。两种 Windows 构建都不要求用户另装 Python；真实 `.m` 运行、`.slx` 写入和仿真仍需要 MATLAB/Simulink。

## 可选 AI 助手

AI 是助手层，不是工作台本身。当前内置 BYOK Provider 包括 OpenAI、DeepSeek、Kimi/月之暗面、MiniMax、GLM/智谱、Qwen/阿里云百炼，以及自定义 OpenAI-compatible endpoint。

对 SLX，Agent 使用结构化模型工具和校验后的 Blueprint，而不是默认获得任意 MATLAB Shell。外部程序可以使用 [`docs/agent-api.md`](docs/agent-api.md) 中的本地 REST API。

## 可选 Git / Review 工具

原来的 `slx-diff` 能力继续保留：

```bash
slx-diff diff before.slx after.slx
slx-diff review before.slx after.slx
slx-diff context before.slx after.slx
slx-diff git-diff --base main --head HEAD
```

这些能力可以在不启动 MATLAB 的情况下给出 Block / Parameter / Connection 语义差异、静态影响路径和紧凑 AI Context。

## 架构

```text
┌────────────────────────────────────────────┐
│              SLX Studio Workbench          │
│                                            │
│ 项目树       .m 多标签        .slx 画布     │
│              编辑器           Inspector     │
│              Console          Block Palette │
│              Variables        Undo / Redo   │
└────────────────┬──────────────────┬────────┘
                 │                  │
              文本保存/运行       结构化编辑
                 │                  │
                 └────────┬─────────┘
                          ▼
                    本地 Python Bridge
                          │
             ┌────────────┴────────────┐
             ▼                         ▼
       可选 AI Provider             本地 MATLAB
        受限工具调用               run / edit / sim
```

## 当前限制

v1.0 Beta 仍然是“小型工程编辑器”，不是 MATLAB 替代品：

- 暂无完整 MATLAB Language Server、Debugger、Breakpoint、Profiler；
- Workspace Variables 已支持显式表达式修改，但还不是完整的表格式数组编辑器；
- `.m`、SLX Simulation 和 Parameter Sweep 都支持 Stop；Command Window 命令目前仍是同步请求，尚不能单独中途停止；
- stdout / stderr 目前在 MATLAB Job 完成后回收，还不是实时流式 Console；
- SLX 已能按已有连接显示明确多端口，但动态/条件端口语义和高级 Simulink 对象还需要继续适配；
- 静态解析会在 `metadata.unsupported_features` 中显式报告 Stateflow、Mask、Variant、Library Link、Model Reference、Bus/Data Type 元数据、动态/条件端口，以及安全目录之外的 BlockType。它们仍可用于查看/Review，但不宣称可完整编辑或语义完整；
- 一旦出现这些提示，参数、端口、编译、仿真和保存必须回到 MATLAB/Simulink 做权威验证。静态图结果不是稳定性、安全性或鲁棒性证明；
- 真实 MATLAB R2026a 集成测试只有在显式设置 `SLX_STUDIO_MATLAB` 或 `SLX_DIFF_MATLAB` 时才启用。GitHub hosted runner 不包含 MATLAB；`.github/workflows/matlab-self-hosted.yml` 只是手动 self-hosted 模板；
- 仓库已配置 Windows 便携 EXE + Setup EXE 工作流，但当前环境不是 Windows，因此不会虚报这两个 Windows 二进制已经在本机验证。

## 测试

```bash
python -m pytest -ra
python -m pytest --collect-only -q
python -m ruff check .
python -m ruff format --check .
```

v1.0 Beta 当前收集到 **80 项测试**（其中 1 项真实 MATLAB 集成测试默认跳过，只有显式配置 MATLAB 路径才运行），覆盖 XML/归档安全、REST 输入错误、SLX Parser/Diff/Review、Patch、AI Blueprint/Provider、Workspace 隔离、Section 运行、可停止 MATLAB Job、共享 Command Session checkpoint、恢复草稿、Parameter Sweep 与指标、Figure 回传、SimulationOutput 曲线提取、工程搜索、Save As、模型历史、多端口 UI 契约和 Workbench HTTP API。

在安装了 MATLAB R2026a + Simulink 的机器上显式运行真实验收：

```powershell
$env:SLX_STUDIO_MATLAB = 'C:\Program Files\MATLAB\R2026a\bin\matlab.exe'
python -m pytest -ra -m matlab_integration
```

该入口覆盖 `set_param`、`add_block`、`delete_block`、`add_line`、`delete_line`、`save_system`、`sim`、Figure 导出和 Workspace checkpoint；它与 fake MATLAB 协议测试互补，不能互相冒充。

## License

MIT。MATLAB / Simulink 属于 MathWorks，本项目不包含 MATLAB 或 Simulink 本体。

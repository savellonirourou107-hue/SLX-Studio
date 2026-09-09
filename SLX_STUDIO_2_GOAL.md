# SLX Studio 2.0 项目目标

状态：**2.0 核心迁移已完成 M0b–M4 验收，准备合并 `main` 并发布 `v2.0.0`。**

本目标依据维护者于 2026-09-07 提供的架构意见制定。
实施细节、现有分支依赖和验收门槛见 [迁移总纲](docs/slx-studio-2-migration.md)。

## 产品方向

**SLX Studio = 面向 MATLAB / Simulink / 控制工程的 Model + Code + Simulation-first IDE。**

借鉴 VS Code 的分层工作台和扩展机制，不复制其品牌、不承诺兼容它的插件，
也不把“长得像 VS Code”当作项目验收。
在同一工作台内，让代码、模型、仿真结果与控制分析成为一等公民。

核心工程闭环是：

```text
打开可信工程
  → 编辑 .m / 检查 .slx
  → 在明确授权下运行或修改
  → 查看变量、图形、诊断与仿真结果
  → 对照差异、保存并复现实验
```

## 已选择的架构方向

| 层 | 目标与边界 |
| --- | --- |
| Desktop | Electron；与旧版 pywebview / 浏览器入口并行迁移 |
| Workbench | TypeScript 模块；先用原生 DOM，不为外观引入整套 UI 框架 |
| Text Editor | 本地打包的 Monaco；一个文件对应一个受管理的 TextModel |
| Platform | Commands、Services、Settings、Editor / View / Panel 注册机制 |
| Transport | 受限 Electron IPC；逐步接入 Python JSON-RPC，保留现有 REST 兼容入口 |
| Engineering | 保留 `src/slxdiff` 的 Python parser、canonical model、diff、校验和 MATLAB bridges |
| Runtime | 接续已有常驻 MATLAB worker，完善生命周期并统一运行能力 |
| Extensions | 独立、按需启动的 Node.js Extension Host；先做可信首方扩展 |

## 必须保留

- Python 核心无强制运行依赖；`slx-diff` CLI 可脱离 Electron 单独使用。
- `.slx` 静态 ZIP/XML 检查不启动 MATLAB，不执行模型 callback 或嵌入代码。
- 模型写入仍经校验与真实 MATLAB/Simulink API，不由前端直接重写私有 SLX XML。
- 源文件哈希冲突检查、原子保存、Undo/Redo、防丢稿和明确的错误反馈。
- 现有 CLI / REST 的兼容路径及测试；迁移完成前不删除旧版入口或 HTML。
- MATLAB 使用用户自己的安装与许可证，不捆绑 MATLAB，也不接管已有用户会话。

## 轻量化的定义

Electron 将增加基础桌面运行时成本，因此不承诺与当前 WebView 包等体积。
轻量化必须表现为可测量的边界：

- 不安装桌面端，也能使用 Python 核心。
- 空工作台不启动 MATLAB、不加载全部扩展、不扫描整个磁盘。
- Monaco、模型渲染、工程索引和扩展按需加载，并能释放资源。
- 默认无遥测、无 AI 网络请求；模型与代码不自动上传。
- 每个里程碑提交启动时间、进程内存、包体积和大工程样例数据；
  MATLAB 本身的成本单列，不混入或隐去。
- 性能目标见迁移总纲；**目标值不是已测量结果**。

## 核心里程碑

- [x] M0a：记录目标、当前基线、保留清单、架构决策和验收方案。
- [x] M0b：审查并整合分散分支中的必要修复，形成可追溯的迁移基线。
- [x] M1：Electron + Monaco 首个真实编辑闭环，带 Commands / Services 基础。
- [x] M2：模块化 Workbench、配置分层与受测的 Python JSON-RPC 适配（本地验收）。
- [x] M3：SLX Custom Editor 与已有 MATLAB 常驻能力接入同一工作台，并通过完整模型/代码/仿真 UI 验收。
- [x] M4：独立 Extension Host、稳定的小型 API、首方扩展及实际安装/关闭重开/卸载验收。

M1 的完成定义不是截图：必须能打开真实工程、打开与切换 `.m` 标签、编辑、
Undo/Redo、保存、处理外部修改冲突与未保存关闭，且通过 Electron 实际运行测试。

2.0 核心目标已在 M0b–M4 全部通过各自验收后完成。
每阶段的测试范围、已知限制和未实现功能必须公开区分。

## 后续路线，不冒充当前能力

完整 MATLAB LSP、真正可暂停/单步的 Debugger、Profiler、Remote 和 Marketplace
在平台核心稳定后分开实施。控制分析、Terminal、Git 和 AI 能力按扩展边界接入；
当前没有这些能力的入口不得伪装成可用功能。
Monaco 的语言着色不等于 MATLAB 语义补全；现有 tracepoints 不等于交互调试器。

## 交付约束

- 使用独立开发分支和可审查的小变更，不能一次清空或重写整个项目。
- 不擅自合并既有 GitHub PR、强推 `main` 或移动旧 tag；正式发布由维护者按验收记录执行。
- 规划文档与验收记录必须同步实现状态；已完成能力以测试和发布资产为准。
- 涉及 MATLAB/Simulink 行为的变更必须补测试，用本机真实 R2026a 验证。
  Python 替身测试、真实引擎测试、桌面 UI 测试和打包检查分别报告。
- 发现真实 bug，先复现、修复、补回归，再推进下一阶段；不跳过失败验收。
- 改架构不等于获得用户工程内容上传、后台自动执行或第三方代码运行的授权。

## 当前接力点

当前发布候选已完成 M0b–M4，证据见
[M1 验收记录](docs/slx-studio-2-m1-evidence.md)与
[M2 基础验收记录](docs/slx-studio-2-m2-foundation.md)与
[M3/M4 核心验收记录](docs/slx-studio-2-m3-m4.md)。当前模型视口仍只读、静态且不宣称
Simulink 绘制等价；保留 Python 源码位置和现有启动命令。

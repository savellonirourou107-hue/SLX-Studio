# 2026-09-16：安全、Subsystem 与编辑辅助验收

范围：评审建议的 Phase 0–2，以及后续 Control Lab 的能力契约。
**没有实现 Control Lab，也没有新建 Release 或替换 `v2.0.0` 资产。**

基线：`7822f07`。Subsystem / 编辑辅助代码提交：`4f2d5d2`；MCP 追加编码修复：`8ed4fee`；
Windows MATLAB console 修复：`bee767a`（最终运行代码候选）。
后续文档提交不会改变这些运行路径。测试使用合成/自行生成的小模型，未上传用户工程。

## 分项证据

| 类别 | 本机结果 | 边界 |
| --- | --- | --- |
| Python | `207 passed, 12 skipped`，21.92 s | 默认命令不启用真实 MATLAB；1 项 symlink 测试因本机权限跳过，不计通过 |
| Ruff / compileall | PASS | 静态检查不是运行时证据 |
| TypeScript / platform | PASS，19 tests | 包含词法、嵌套调用、UTF-16、版本缓存、200 ms debounce、大小限制、释放和进程协议 |
| 实际 Electron | PASS | 补全弹窗、本地变量、工具箱 hover、实时参数高亮、空容器导航、原有编辑保存/恢复/扩展失效工作流；100 次开关后无保留 TextModel/符号缓存 |
| 实际 R2026a | **11 passed**，440.61 s | 覆盖本轮旧桥接回归与 Subsystem 事务；只代表已覆盖模型/版本 |
| R2026a + Electron | **PASS** | `npm run test:matlab-desktop`；不是上方无 MATLAB 的 Electron 测试 |
| Windows 打包/安装 | **PASS**，Run `35127966783` | 两个 job 均成功；Electron 包真实安装、启动、重开与卸载通过 |
| GitHub CI | **PASS**，Run `35127939191` | Python 3.10–3.14 + Windows session；GitHub hosted CI 未运行 MATLAB |

MATLAB 库默认探针实际观察到普通 Subsystem 含 In1、Out1、1 条连接。
新增容器通过官方 API 清理默认内容后，再按事务添加显式子块。
`tests/test_subsystem_r2026a.py` 覆盖保存/重解析/再加载、3 个子块/2 条线、
根层结构保留、重命名、删除、精确字节 Undo/Redo、外部 SHA 冲突。

### 失败记录

- MCP workspace 绝对路径越界、超长整数解码失败和 JSON 转义 surrogate 响应编码失败，
  均已补回归测试并修复；异常输入后下一条合法请求仍然可以处理。
- 增加空容器 UI fixture 后，旧测试固定的标签总数断言失败；测试现在主动关闭
  该临时标签，完整 `check:desktop` 重跑通过。没有把测试 fixture 问题当作产品 bug。
- 初次完整真实 MATLAB 序列为 10 passed / 1 failed，新 Subsystem 编辑任务失败，
  原断言折叠了错误字段。已改为优先展示后台错误，单独重跑 1 passed / 175.70 s。
- 第二次完整序列同样为 10 passed / 1 failed；这次在删除阶段启动 MATLAB 时
  捕获 **Error 5001**。这是 MATLAB 启动所需许可服务不可用，参见
  [MathWorks 支持说明](https://www.mathworks.com/support/lme/5001)，不能误称模型编辑失败。
  随后独立启动检查通过 `SLX_STARTUP_OK_R2026A`；未重装服务、删除许可数据或重启用户会话。
- 同时发现 batch console 把 Windows 系统编码错误当 UTF-8，导致中文诊断乱码。
  已修复并添加 CP936/UTF-8 分片解码、EOF 不完整字节测试。没有添加自动重放或
  将许可失败算作跳过的逻辑；完整门槛重新执行，原始失败 JUnit 保留在本地。
- 最终完整序列为 **11 passed**；随后实际 Electron + MATLAB 联验也通过。

### GitHub evidence

- [PR #24](https://github.com/savellonirourou107-hue/SLX-Studio/pull/24)
- [CI](https://github.com/savellonirourou107-hue/SLX-Studio/actions/runs/35127939191)：
  Linux Python 3.12 示例为 `204 passed, 15 skipped`；平台差异不与 Windows 总数混加。
- [Build Windows desktop](https://github.com/savellonirourou107-hue/SLX-Studio/actions/runs/35127966783)：
  `windows-exe` 1m18s；`electron-windows` 4m50s。构建目标为 `921cc5e`，
  后续仅补验收文档；未发布新 Release，也未移动旧 tag。
- 非阻断 warning：既有 `actions/upload-artifact@v4` 使用 Node 20 声明，runner
  将其切换至 Node 24；两个上传步骤实际均成功。

## 轻量性

Python 强制运行依赖仍为零，Node 依赖清单未增加条目；没有引入语言服务器、
网络目录查询或新 UI 框架。缓存及 provider 上限见[编辑辅助说明](matlab-intelligence.md)。
新一轮 `measure:desktop` 使用 10 次新进程、同一生成的单文件工作区；OS 文件缓存
不清空，Playwright instrumentation 开启，杀毒环境不控制。测量时未运行 MATLAB。

| 指标 | 实测 | 既定预算 |
| --- | --- | --- |
| 编辑器接受输入，10 次中位数 / 最大值 | 800.55 / 826.75 ms | ≤ 3,000 / 5,000 ms |
| ready 时 Electron private memory 最大值 | 281.77 MiB | 单列，不冒充总进程内存 |
| ready 后 30 s 所有自有进程 private memory | 260.35 MiB | ≤ 350 MiB；包含 Python，排除 MATLAB |

机器：Windows 10.0.26200 x64、i9-13900H、32 GiB RAM。
原始报告由 `scripts/measure-desktop.mjs` 生成，保存在忽略的
`output/measurements/desktop-m2-foundation.json`，时间 `2026-09-16T16:55:09Z`。
报告的 `dirty: true` 对应当时尚未提交的文档修改，运行代码为 `4f2d5d2`。
这是一次本机资源验收，不是相对旧版的提速声明或大工程性能保证。
10 次原始 ready 时间（ms）：`826.75, 802.90, 790.24, 772.82, 773.03,
811.10, 777.50, 819.15, 820.78, 798.19`。

Actions 的 Electron 合并 artifact 为 277,759,781 bytes（264.89 MiB），同时包含
portable 目录和 installer；旧版合并 artifact 为 36,989,299 bytes（35.28 MiB）。
前者超过 250 MiB 的单 artifact 目标，不能声称所有体积预算已达标。
单独分发包压缩大小和安装占用本轮未另测；本轮已达标的是启动/空闲内存和依赖边界。

## 复现命令

```powershell
python -m pytest -ra
python -m ruff check .
python -m ruff format --check .
python -m compileall -q src tests
npm run check:desktop
npm run measure:desktop
$env:SLX_STUDIO_MATLAB = '<licensed R2026a>/bin/matlab.exe'
python -m pytest tests/test_matlab_r2026a_integration.py tests/test_persistent_matlab_integration.py tests/test_subsystem_r2026a.py -v -ra -o addopts=
npm run test:matlab-desktop
```

本机：Windows，PowerShell 7.6.5，Python 3.13.5，Node 24.14.1，Electron 44.2.0，
真实 MATLAB/Simulink R2026a。TEMP/TMP、Python 缓存、MATLAB preferences 和 UI 状态
均指定到 E 盘；实验不使用或修改已打开的用户模型。
未验证其他 MATLAB release、复杂 Subsystem 语义或完整 LSP。

## English summary

This iteration implements review phases 0–2: MCP workspace/message hardening,
plain Subsystem edit transactions, and bounded offline MATLAB editor assistance.
Control Lab remains a design contract; Issue #6 must stay open. Python, actual
MATLAB, actual Electron and Windows packaging evidence are reported separately.
Skipped tests are not passes. Existing `v2.0.0` release assets are unchanged.

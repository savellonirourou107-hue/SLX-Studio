# Control Lab：能力边界与分阶段验收 / capability contract

状态：设计约束已明确，**尚未实现 Control Core / Control Lab**。Issue #6 保持开放。
本轮先交付 MCP 安全修复、最小 Subsystem 工作流和轻量 MATLAB 编辑辅助。

## 架构与依赖

- Python 核心继续 `dependencies = []`，不自行实现通用多项式求根、特征值或 SciPy 替代品。
- `control_core.py` 仅负责有界请求/结果契约、纯计算 kernel 与 MATLAB bridge。
- 两个显式后端：`python-lite` 与 `matlab`。不静默从一个后端切换到另一个；
  每次返回 backend、算法/容差、输入、limitations、run identity，MATLAB 再返回 release/toolbox。
- UI、绘图、命令、PID 工作流放在 `firstparty.control` 扩展和 `packages/control`，
  通过最小、受校验的服务 capability 接入。不能把新面板或控制业务塞回旧 HTTP 主干。
- 不启动扩展/MATLAB直到用户显式分析。缺少许可证/工具箱返回 capability unavailable，
  不以假数据代替，也不自动运行工作区代码。

## Control Core M0 的数学契约

| 项目 | 第一阶段定义及拒绝边界 |
| --- | --- |
| 输入 | 连续时间 SISO、有限实系数、降幂系数、proper TF；分母阶数 ≤ 6，输出采样点 ≤ 2000；先归一化，零分母/数值溢出拒绝 |
| Python-lite 频响 | 直接计算 `N(jw)/D(jw)`；频率严格为正、有限、递增；分母近零点显式标记，不输出伪造有限值 |
| Python-lite step | controllable canonical state-space + 有误差估计和工作量上限的 RK 积分；stiff/误差预算不足则返回 unsupported，不自行求全部极点 |
| Step 指标 | rise time 10%→90%，settling time ±2%，peak time、overshoot、final value；积分/发散/有限时窗未收敛时指标为 null 并解释，不拿末样本冒充稳态 |
| 误差名称 | `unit_step_tracking_error = 1 - final_value` 只在明确解释为 reference→output 时计算，不泛称 `steady_state_error` |
| Margin | gain_margin_db、phase_margin_deg、gain_crossover_rad_s、phase_crossover_rad_s；报告全部检测到的 crossover 与选取规则，有限频率网格不构成全局稳定性证明 |
| Margin 数值细节 | phase unwrap 后在 log-frequency 上线性插值；切线/多次交叉/网格边界给出不确定性；无交叉返回 null + `not_found_in_range`，数学无穷用 null + `infinite` 状态，严格 JSON 禁止 NaN/Inf |
| Nyquist | 第一版仅正频率分支，返回 `contour: positive-frequency-branch`；不据此声称完整 Nyquist 绕数或稳定性判据 |
| PID | 只给 `heuristic seed`，方法和适用性明确；非 FOPDT-like、非最小相位、不稳定、积分或不足以判断时 `eligible=false` + reason；必须另做闭环验证 |
| MATLAB | 手动 TF/SS 经 `tf`/`ss` 和 `step`/`bode`/`nyquist`/`margin` 等官方 API；必须检测 Control System Toolbox 并记录实际 release |

低阶和有界数组不保证数值问题良态；Python-lite 不承诺通用稳定性判断。
在 step 积分误差、刚性拒绝和收敛判据通过 golden/differential gates 前，不向用户开放 step/PID。

## 后续交付顺序

1. **Control Core M0**：请求/后端契约、有限频响、step 与指标、margin、受限 PID seed；
   只有数值核不代表完整 Control Lab，不能关闭 Issue #6。
2. **Control Lab 扩展**：真实参数编辑、Step/Bode/Nyquist 图、指标卡、PID 工作区和
   extension activation/disposal/E2E；不额外引入大型 UI 框架。
3. **SLX 线性化**：用户明确选择输入/输出、operating point 和模型配置，再检测
   Simulink Control Design 并调用 `linearize`；当前不宣称自动从任意 SLX 得到线性系统。
4. State-space 全面分析、LQR/MPC、航空/机器人工作流另行定范围；未交付前保持 Issue #6 开放。

## 发布前门槛

- Golden：`1/(s+1)` 在 `w=1` 的幅值 `-3.0103 dB` 和相位 `-45°`，各误差 < `1e-3`；
  一阶 step 对解析解的最大绝对误差 ≤ `1e-5`（时间/采样/积分容差写入 fixture）。
- 一阶/二阶、积分、不稳定、多 crossover、重根/近重根、病态系数、极端时间尺度、
  improper 与不符合 PID 假设的输入必须分别测试，拒绝/不确定也是正确结果。
- MATLAB differential：同一输入和频率/时间网格，与真实 R2026a 输出逐项比较；
  先冻结每类问题的容差，失败不能通过放宽容差掩盖。记录工具箱和 license 可用性。
- 协议拒绝越界路径、超限负载；响应序列化用严格 JSON；UI 显示 backend/limitations。
- Python 全量、TypeScript、平台协议、真实 Electron 交互及扩展释放回归全部通过。
- 文档分开报告 unit / numerical / real MATLAB / desktop / packaging；跳过不计通过。

## English summary

This is a **design contract, not an implemented Control Lab**. Keep a dependency-free,
bounded Python-lite backend and an explicit MATLAB backend with toolbox/release provenance.
Do not implement a general polynomial-root solver. Restrict v1 to continuous-time proper
real SISO transfer functions (denominator order ≤ 6, samples ≤ 2000). Reject numerically
unsupported cases; never infer steady state from the last sample or global stability from
a finite frequency grid. PID values are heuristic starting points, not guaranteed tuning.
The UI belongs to `firstparty.control`; manual TF/SS comes before an explicit SLX I/O and
operating-point linearization workflow. Issue #6 remains open until its actual user-facing
scope is delivered and verified with golden, MATLAB differential and Electron tests.

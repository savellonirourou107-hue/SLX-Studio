# Subsystem 编辑 / Subsystem editing

本功能属于 `v2.0.0` 之后的源码改进，不会自动出现在原有 Release 安装包中。
静态查看不启动 MATLAB；创建、修改与保存仍需要本机 MATLAB/Simulink 和可信模型。

## 使用方法

1. 在旧版 `slx-studio <workspace>` Workbench 打开 `.slx`，进入添加模块面板，
   搜索 `subsystem`，输入名称并点击创建。创建按钮会立即经 MATLAB 保存，
   不需要再点击参数面板的 **Apply in MATLAB**。
2. 双击新 Subsystem 或使用层级选择器进入。空容器也能导航；添加
   Inport、Gain、Outport 后，用现有连线操作连接同层端口。
3. 修改、重命名或删除仍走原有验证和历史记录。外部修改导致 SHA-256 不匹配时，
   先重新加载；旧的修改或 Undo 不会覆盖外部版本。

Electron 桌面保留只读静态视口。其 **Simulink: Apply Validated Model Edit…**
命令支持同样的 JSON 编辑事务；这不是新增的拖拽框图编辑器。
下面的 `operations` 可以放进现有 `schema_version: "0.1"` 文档，
同时提供当前 `model_name` 和 **当前文件的** `source_sha256`：

```json
[
  {"op":"add_block","block_type":"subsystem","name":"Controller","parent":""},
  {"op":"add_block","block_type":"inport","name":"In1","parent":"Controller","parameters":{"Port":"1"}},
  {"op":"add_block","block_type":"gain","name":"Gain","parent":"Controller","parameters":{"Gain":"2"}},
  {"op":"add_block","block_type":"outport","name":"Out1","parent":"Controller","parameters":{"Port":"1"}},
  {"op":"add_line","system_path":"Controller","src_path":"Controller/In1","dst_path":"Controller/Gain"},
  {"op":"add_line","system_path":"Controller","src_path":"Controller/Gain","dst_path":"Controller/Out1"}
]
```

上例省略了可选位置，仅用于说明事务；正式布局可为每个模块指定
`position: [left, top, right, bottom]`。路径相对模型根，大小写敏感；
新名称不接受 `/`。连线必须声明两个端点的**直接父层级**，不能跨层直连。

## 已验证行为与边界

- 本机 R2026a 实测：库里的普通 Subsystem 默认含 In1、Out1 和一条线，
  并非空容器。bridge 只对**本次刚新建的容器**调用
  [`Simulink.SubSystem.deleteContents`](https://www.mathworks.com/help/simulink/slref/simulink.subsystem.deletecontents.html)，
  再执行显式子块操作；绝不清空已有用户 Subsystem。
- BlockType 使用目录中的规范值，例如 `SubSystem`、`TransferFcn`、`UnitDelay`；
  不从目录键猜大小写。每个待创建容器有独立的虚拟 system identity。
- 同一事务可以新建父容器、子块、内部线，也可以按顺序重命名、删除或重新创建。
- 静态检查拒绝重复块名、已知越界/反向端口、错误层级和跨层连接；
  动态端口和复杂 Simulink 语义仍以 MATLAB 为准。
- 这里只支持普通 Subsystem。Masked/linked/variant 容器、触发/使能语义、
  Stateflow 和模型引用不因此获得完整编辑支持。
- catalog 将 `allow_model_edit` 和 `allow_blueprint` 分开。Subsystem 当前
  **只用于模型编辑**；无层级定义的 Blueprint 仍拒绝它，包括直接构造的 Python 对象。

自动验收位于 `tests/test_subsystem_edit.py` 和 `tests/test_subsystem_r2026a.py`。
真实 MATLAB 测试涵盖创建、保存、静态重解析、MATLAB 再加载、内部连线、
重命名/删除、精确字节 Undo/Redo，以及外部修改冲突。

## English

Use the legacy Workbench's Add Block panel to create a plain `subsystem`, then
double-click it to add child blocks and connect ports in that immediate scope.
Creation saves through MATLAB immediately. The Electron viewport remains read-only;
its validated JSON edit command accepts the same transaction shown above.

The bridge clears library-default contents **only on a newly created container**.
Existing Subsystems are never cleared. Canonical catalog types and distinct virtual
system identities prevent accidental cross-level wiring. Saved models are covered by
real R2026a reparse/reload and history/conflict tests. Masked, linked, variant and
conditional execution semantics are not generally supported. Subsystems remain
disabled for the flat Blueprint format. Existing release binaries are unchanged.

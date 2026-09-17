# MATLAB 轻量编辑辅助 / Lightweight editing assistance

本功能在 Electron/Monaco 源码桌面中运行，不需要启动 MATLAB、连接网络或安装 LSP。
它不是完整的 MATLAB 语义服务，也不会检查本机工具箱许可证。
`v2.0.0` 原安装包未包含本次改动；从当前源码构建体验。

## 怎么使用

- **补全**：在 `.m` 文件中输入 `plo`，按 `Ctrl+Space`，选择 `plot`。
  当前文档中的赋值变量、循环变量、函数名、参数和输出名会出现在本地符号建议中。
- **悬停**：将鼠标停在 `tf`、`bode`、`sim` 等函数上，查看常用签名、简述和产品标签。
- **参数提示**：输入 `plot(`，再输入参数和逗号；当前参数高亮会随之切换。
  字符串、矩阵和嵌套调用中的逗号不会被直接算作外层参数分隔符。

目录目前是精选的 39 个常用函数，区分 MATLAB、Simulink、Control System Toolbox
和 Simulink Control Design。例如 `tf` 的提示明确标注 Control System Toolbox；
出现提示不代表该函数在当前 MATLAB path 中可用，也不表示已经实现 Control Lab。

## 轻量性与已知限制

- 一个 Monaco TextModel 对应一个词法符号缓存；以 document version 避免重复扫描，
  内容修改后静默 200 ms 再更新。补全请求读取缓存，不逐次全文件扫描。
- 超过 250,000 个 UTF-16 code units 的文件停止本地符号索引；最多保留 1,000 个符号。
  提供器只读取光标前最多 12,000 个 code units 的上下文。
- 文件关闭时释放缓存、定时器和监听器。自动桌面测试包含 100 次打开/关闭检查。
- 符号仅是词法线索，不做跨文件/类/作用域分析、类型推断、MATLAB path 解析或重命名。
  同名本地符号会遮蔽离线目录提示；复杂转置/字符串歧义、跨越上下文窗口的语法、
  多行声明等可能不能准确识别。目录只给精选签名，不覆盖所有重载和 name-value 组合。
- 不增加 Python 强制依赖、运行中的语言服务器或新的前端框架。

实现位于 `packages/editor/matlab-{catalog,language,intelligence}.ts`。
`npm run test:platform` 检查词法/缓存契约，`npm run check:desktop`
在真实 Electron 中检查补全列表、悬停内容、参数提示和释放行为。

## English

In an Electron `.m` editor, press **Ctrl+Space** for completions, hover over a
curated function for signatures and product requirements, and type `(` or `,`
for parameter hints. The offline catalog contains 39 common functions. Suggestions
also include current-document lexical symbols; toolbox labels do not prove installation.

This is **lightweight assistance, not an LSP**. No MATLAB process or network access
is required. Local symbols are version-cached with a 200 ms debounce, bounded to
250,000 UTF-16 code units and 1,000 symbols. Provider context is capped at 12,000
code units. Closing a model releases its listeners and timers. Cross-file/type/scope
inference, class completion and comprehensive MATLAB syntax/name resolution are
outside this implementation. Rebuild from source; old release binaries do not change.

# AI Daily Brief 开发约束

- 运行时要求 Python 3.12+。
- Provider 和 Model 禁止硬编码，必须通过配置、环境变量或 CLI 传入。
- Secret 只能从环境变量或 CI Secret 读取，不得写入源码、YAML、Git 或普通日志。
- Collector 之间必须故障隔离；单个外部数据源失败不能中断整条日报流程。
- 所有外部 HTTP 请求必须显式设置 timeout，并只对 timeout、连接错误、429、502、503、504 等适合重试的错误 retry。
- 业务代码不得直接实例化 Provider SDK；只能依赖 `LLMClient` 与 `ModelRouter`。
- URL 必须来自真实抓取内容，LLM 不得生成不存在的引用链接。
- 配置优先于硬编码；兴趣主题、数据源、人物、评分权重均应优先放在 YAML。
- 日志必须脱敏，不得记录 API Key、完整认证 Header 或敏感请求体。
- 新功能必须补 Mock 测试，测试禁止调用真实 LLM、外部 API 或推送渠道。
- 修改完成后至少运行 `pytest`，并在条件允许时运行 `--show-models` 和 `--dry-run`。
- 保留原始 ContentItem 粒度和全部真实来源 URL，不用去重结果替代原始订单式记录。


"""Repository 层：纯 CRUD，每表一个 Repository，命名 XRepository。

职责：单表读写、查询条件构造。不包含业务逻辑、不调用 LLM、不直接发 HTTP。
业务逻辑放 app/services/，事务由 AppSvc 管理。
"""

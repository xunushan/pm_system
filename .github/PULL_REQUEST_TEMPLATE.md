## 本 PR 实现内容
<!-- 列出新增/修改的表、端点、逻辑 -->

## 关联
- Story: <!-- 如 S1 -->
- 依赖: <!-- 如 无 / S1已合并 -->
- Fixes #<!-- issue 号，若修了 issue -->

## 实现清单（对照 CLAUDE.md）
- [ ] 新增/改动的 model 已建（app/models/*.py，自动发现无需改 __init__）
- [ ] 迁移已生成并 `make upgrade` 验证（`alembic/versions/`）
- [ ] Repository 层（如需）
- [ ] AppSvc（业务+事务+级联，事务内禁 IO）
- [ ] 路由（app/api/v1/*.py）
- [ ] 复用了 app/core / app/clients 现有件，未重写

## 测试
- [ ] `make test` 全绿
- [ ] 新增单元测试（级联/状态机/推断等）
- [ ] 新增集成测试（API + DB）

## 自检（架构铁律，见 CLAUDE.md 第三节）
- [ ] Service 未调用 LLM
- [ ] 确认类 API 仅 DB 写+即时级联（<200ms）
- [ ] 事务内无 IO/HTTP
- [ ] drafts 确认按钮只传 draft_id（若涉及）
- [ ] 状态流转写 status_change_log（若涉及）

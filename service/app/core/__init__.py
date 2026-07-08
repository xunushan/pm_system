"""跨 Story 复用的核心件：即时级联 / 状态机校验 / 状态变更审计。

**复用纪律（见 CLAUDE.md「复用件清单」）**：
所有 Story 实现状态变更相关逻辑时，必须复用本目录的现成件，禁止重写。

  cascade        即时级联引擎（任务/阶段状态变更时事务内向上推导）
  state_machine  状态机校验（状态流转合法性 + reason 必填性）
  audit          状态变更审计（写 status_change_log）

用法：
    from app.core import cascade, state_machine, audit
"""

from app.core import audit, cascade, state_machine  # noqa: F401

__all__ = ["cascade", "state_machine", "audit"]

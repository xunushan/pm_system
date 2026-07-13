"""E2E S1 验证：用户点击「确认方案」后，验证落库 + 删 draft + update_card 刷新。

通过判据（TEST_PLAN TC-S1-01）：卡片刷新 + 4 表有数据 + draft 表该条消失 + 无异常。
"""

from sqlalchemy import text

from app.db.session import engine

DRAFT_ID = "d61be821-b6c1-4c84-a764-5d901c1896ed"


def main() -> None:
    print(f"=== S1 验证（draft_id={DRAFT_ID}）===\n")
    ok = True
    with engine.connect() as c:
        # 1. 4 张正式表落库
        goal_n = c.execute(text("SELECT COUNT(*) FROM goals")).scalar()
        theme_n = c.execute(text("SELECT COUNT(*) FROM themes")).scalar()
        phase_n = c.execute(text("SELECT COUNT(*) FROM phases")).scalar()
        task_n = c.execute(text("SELECT COUNT(*) FROM tasks")).scalar()
        print(f"[落库] goals={goal_n} themes={theme_n} phases={phase_n} tasks={task_n}")
        if not (goal_n == 1 and theme_n == 4 and phase_n == 4 and task_n == 12):
            print("  ✗ 期望 1/4/4/12")
            ok = False
        else:
            print("  ✓ 1 goal / 4 themes / 4 phases / 12 tasks")

        # 2. draft 已删
        draft_n = c.execute(
            text("SELECT COUNT(*) FROM drafts WHERE id=:id"), {"id": DRAFT_ID}
        ).scalar()
        print(f"[删draft] drafts 该条 = {draft_n}")
        if draft_n != 0:
            print("  ✗ draft 未删（确认未生效或并发问题）")
            ok = False
        else:
            print("  ✓ draft 已删除")

        # 3. goal 名称 + 初始状态（规划态未开始）
        row = c.execute(text("SELECT name, status FROM goals LIMIT 1")).fetchone()
        if row:
            print(f"[goal] name={row[0]} status={row[1]}")
            if row[0] != "知识库构建" or row[1] != "未开始":
                print("  ✗ 期望 name=知识库构建 status=未开始")
                ok = False
            else:
                print("  ✓ goal 名称+规划态初始状态正确")
        else:
            print("  ✗ goal 表为空")
            ok = False

        # 4. executor 规划态不填（铁律 §8）
        null_exec = c.execute(
            text("SELECT COUNT(*) FROM tasks WHERE executor IS NOT NULL")
        ).scalar()
        print(f"[铁律§8] tasks.executor 非空数 = {null_exec}")
        if null_exec != 0:
            print("  ✗ 规划态 executor 应为 NULL")
            ok = False
        else:
            print("  ✓ 12 任务 executor 全 NULL（pm-daily 按专题推断）")

        # 5. phases.deadline 规划态不填（铁律 §8）
        nonnull_dl = c.execute(
            text("SELECT COUNT(*) FROM phases WHERE deadline IS NOT NULL")
        ).scalar()
        print(f"[铁律§8] phases.deadline 非空数 = {nonnull_dl}")
        if nonnull_dl != 0:
            print("  ✗ 规划态 deadline 应为 NULL")
            ok = False
        else:
            print("  ✓ 4 阶段 deadline 全 NULL（激活时填）")

    print()
    print("=== 结论 ===")
    print("✅ S1 落库链路通过" if ok else "❌ S1 有未通过项，查日志")


if __name__ == "__main__":
    main()

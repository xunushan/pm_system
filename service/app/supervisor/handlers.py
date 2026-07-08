"""事件处理：阶段完成 -> 查下一阶段 + 推算 deadline + 推衔接卡片。

确定性代码（非 LLM，符合"减少 Skill"原则）：
  Step1 查同专题 sort_order+1 下一阶段（强约束自动锁定）
  Step2 推算 deadline（剩余时间/剩余阶段数）
  Step3 推卡片（含 date_picker + 确认激活/暂不激活）
  Step4 24h 未响应 -> 定时巡检再推一次
详见《系统架构文档》3.3。
"""


def on_phase_completed(phase_id: str) -> None:
    """TODO(Story8)：阶段完成事件 -> 推衔接卡片。"""
    raise NotImplementedError("Story8 实现 - 见 doc/03 3.3")

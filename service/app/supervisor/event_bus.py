"""事件总线：状态变更事件 -> 即时编排 Supervisor。

事件：阶段完成 / 专题完成 / 智能体产出回调 / 任务完成。
TaskAppSvc 在事务内级联后发事件；Supervisor 监听并即时编排衔接。
TODO(Story8)：实现进程内 pub/sub 或基于 Redis 的事件分发。
详见《系统架构文档》3.2。
"""

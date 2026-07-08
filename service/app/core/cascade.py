"""即时级联：任务/阶段状态变更时事务内向上推导。

级联链（纯 DB，与状态变更同事务，<200ms，满足飞书 3 秒回调）：
  任务完成 -> 该阶段任务全完成? -> UPDATE phases='已完成'
         -> 该专题阶段全完成? -> UPDATE themes='已完成'
         -> 该目标专题全完成? -> UPDATE goals='已完成'
         -> 发"阶段/专题/目标完成"事件 -> Supervisor 衔接
  所有级联变更写 status_change_log（change_type='cascade'）。
回退（已完成->进行中/待执行）同样即时重算级联。

详见《数据模型文档 v2.0》2.15 / 《系统架构文档》8.3。
"""


def cascade_status(db, entity_type: str, entity_id: str) -> None:  # noqa: ANN001
    """TODO(Story1 起)：自下而上推导并更新上级状态，事务内。

    返回后由调用方（TaskAppSvc）在事务提交后触发事件总线 -> Supervisor 衔接。
    """
    raise NotImplementedError("Story1+ 实现 - 见 doc/02 2.15")

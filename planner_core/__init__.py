"""planner_core：agent-swarm-planner 的确定性内核。

设计原则：
- 确定性归 Python（状态、DAG、调度、验收、注入），智能归 agent（planner 工作区里的
  任意 agent 用自身模型做拆解决策）。
- 本包不调用任何 LLM / 厂商 SDK。
"""

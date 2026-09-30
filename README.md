# 课表最小扰动修复库（`schedule_repair`）

仅依赖 Python 标准库。给定一张合法的旧周课表和若干新增课节，求**搬动旧课数量最少**的完整课表。

## 模型

- 一周 5 天（`day=0..4`），每天 8 节（`period=0..7`）。
- 课节长度为 1 或 2 个连续节次，不可跨天，全程使用同一教室。
- 每个课节有唯一 ID、固定教师、固定班级、允许起点集合与允许教室集合，两者任意组合。
- 同一节次内教师、班级、教室均不可被两个课节同时占用；连堂占用的每个节次都参与冲突判断。
- `Problem.baseline` 中的课节为旧课，其余为新课；`locked` 中的旧课必须保持基线安排。
- 旧课的周几、起始节次或教室任一变化即计为移动 1 次；新课不计移动。

## API

```python
from schedule_repair import Lesson, Start, Placement, Problem, repair, check

problem = Problem(
    lessons=[...],                 # list[Lesson]，全部旧课 + 新课
    baseline={lesson_id: Placement(Start(day, period), room), ...},
    locked=frozenset({...}),       # 必须保持原安排的旧课 ID
)

result = repair(problem)
# result.feasible : bool
# result.assignments : dict[str, Placement]   全部课节的完整安排（无解时为空）
# result.moved      : frozenset[str]          被搬动的旧课 ID（全局最少）
# result.optimal    : bool                    是否被证明为最优（精确搜索，恒为真）
# result.reason     : str | None              无解原因

checked = check(problem, result.assignments)
# checked.valid  : bool      完整检查：完整性/候选范围/锁定/教师/班级/教室冲突
# checked.moved  : frozenset[str]   根据安排重算的移动集合（不信任 repair）
# checked.errors : list[str]        形如 "RESOURCE_CONFLICT:..." 的错误明细
```

`check` 不证明最优，但完全独立重算合法性与移动集合，可用于校验外部传入的任意安排。

## 算法要点

1. 候选位置按需编码，资源占用用 40 位整数位掩码表示，不展开完整笛卡尔积。
2. 按“共享教师/班级/教室且时间域可能相交”构建交互图并分解连通分量；
   不含新课的分量整体保留基线（时间域已并入基线位置，间接冲突不会被漏连）。
3. 含新课的分量做**移动数预算迭代加深**：预算从 0 递增，配合 MRV、
   锁定课/新课优先、基线候选优先、前向检查与“强制移动数”下界剪枝。
4. 搜索完备：每个预算都完整回溯，预算耗尽绝不报无解；所有预算失败才返回无解。

## 运行全部测试

```bash
python3 -m unittest discover -s tests -v
```

规模测试（200 旧课 + 4 新课以内）中的强制搬迁链实例在本机单核毫秒级完成，
断言上限为 10 秒。

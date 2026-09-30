# 课表最小扰动修复库

纯 Python 标准库实现。固定周模板：一周 5 天、每天 8 节；课节持续 1 或 2
个连续节次、不跨天、课节内使用同一间教室。所有数据在内存中计算，无任何
外部服务、端口或持久化依赖。

## 安装与运行测试

无需安装依赖（需要 Python 3.10+）。在仓库根目录执行：

```bash
python3 -m unittest discover -s tests -v
```

## API

```python
from timetable_repair import Problem, Lesson, Start, Placement, repair, check
```

- `Start(day, period)`：起点，`day` 取 0..4（周一至周五），`period` 取 0..7。
- `Lesson(lesson_id, teacher, klass, duration, allowed_starts, allowed_rooms)`：
  课节定义。`allowed_starts` 与 `allowed_rooms` 各自给出候选集合，二者可任意
  组合；`duration` 为 1 或 2。
- `Placement(start, room)`：一个具体安排。
- `Problem(lessons, baseline, locked_ids)`：
  - `lessons`：全部课节（旧课 + 新课）；
  - `baseline`：旧课 ID 到基线安排的映射，不在其中的课节视为新课；
  - `locked_ids`：必须保持基线安排的旧课 ID 集合。
- `repair(problem) -> RepairResult`：
  - `feasible=True` 时，`assignment` 是包含**全部**课节的完整安排，
    `moved` 是发生移动的旧课 ID 集合；
  - `feasible=False` 表示已穷举证明无解（或问题结构非法，见 `reason`），
    此时不返回任何部分课表。
  - 一个旧课只要周几、起始节次或教室任一变化即计为移动 1 次；新课不计。
- `check(problem, assignment) -> CheckReport`：独立复核，不信任 `repair`
  的任何输出。校验课节完整性、候选范围（起点与教室）、锁定约束、教师/班级/
  教室三类资源冲突（连堂课占用的每一节都参与），并重算移动集合。
  `assignment` 可直接传 `RepairResult` 或 ID→`Placement` 映射。

## 求解方法

- 预处理只按单课节展开候选放置（每节至多 8×4=32 个），内存只与各课节候选
  数之和相关，从不展开全课表笛卡尔积。
- 搜索采用回溯 + 前向检查 + 单值传播，变量按 MRV 选择、取值按
  “基线优先、冲突最少优先”排序；分支定界以当前最优移动数为上界持续剪枝，
  穷举完整搜索空间后才宣布无解，因此不存在超时误报无解的情况。
- 间接冲突由传播自然处理：旧课搬到其他旧课的基线位置会级联迫使后者移动，
  调整范围从不局限于与新课直接冲突的课节；仅换教室、同时换时间与教室的
  方案均正常参与搜索。

## 规模

按 200 节旧课、最多 4 节新课、每节至多 8 个起点与 4 间教室设计。
确定性规模测试（20 节强制搬迁链 + 180 节独立课）在本机单核远低于 10 秒
完成，测试输出会打印实际耗时并断言小于 10 秒。

## 代码结构

- `timetable_repair/model.py`：数据模型。
- `timetable_repair/checker.py`：问题结构校验与 `check` 复核。
- `timetable_repair/solver.py`：候选预处理与最小扰动穷举求解。
- `tests/test_repair.py`：要求的三类场景及补充边界测试。

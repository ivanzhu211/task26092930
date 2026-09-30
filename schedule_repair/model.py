"""课表最小扰动修复库的数据模型。

一周 5 天（0..4），每天 8 个节次（0..7）。
课节长度为 1 或 2，不可跨天。
"""

from __future__ import annotations

from dataclasses import dataclass, field

DAYS = 5
PERIODS = 8


@dataclass(frozen=True)
class Start:
    """课节起点：周几 ``day``（0..4）与起始节次 ``period``（0..7）。"""

    day: int
    period: int


@dataclass(frozen=True)
class Lesson:
    """课节。

    - ``lesson_id`` 全局唯一；
    - ``teacher`` / ``klass`` 为固定教师、固定班级；
    - ``length`` 为持续节数（1 或 2）；
    - ``starts`` 为允许起点集合；
    - ``rooms`` 为允许教室集合；
      允许起点与允许教室可任意组合。
    """

    lesson_id: str
    teacher: str
    klass: str
    length: int
    starts: frozenset[Start]
    rooms: frozenset[str]


@dataclass(frozen=True)
class Placement:
    """课节的完整安排：起点 + 教室。"""

    start: Start
    room: str


@dataclass
class Problem:
    """待修复问题。

    - ``lessons``：全部课节（旧课 + 新课）；
    - ``baseline``：旧课的基线安排（合法），仅包含旧课；
    - ``locked``：锁定旧课 ID 集合，必须保持基线安排；
    - 不在 ``baseline`` 中的课节视为新课。
    """

    lessons: list[Lesson]
    baseline: dict[str, Placement]
    locked: frozenset[str] = field(default_factory=frozenset)


@dataclass
class RepairResult:
    """``repair`` 的返回结果。

    - ``feasible``：是否存在完整合法安排；
    - ``assignments``：``feasible`` 为真时包含全部课节的安排，否则为空；
    - ``moved``：相对基线发生移动的旧课 ID 集合（新课不计）；
    - ``optimal``：``moved`` 是否被证明为全局最小；
    - ``reason``：无解时的明确原因。
    """

    feasible: bool
    assignments: dict[str, Placement] = field(default_factory=dict)
    moved: frozenset[str] = field(default_factory=frozenset)
    optimal: bool = False
    reason: str | None = None


@dataclass
class CheckResult:
    """``check`` 的返回结果。

    - ``valid``：安排是否完整且合法；
    - ``moved``：根据安排重算的移动旧课集合（不信任 repair 的结果）；
    - ``errors``：错误代码与可读信息列表，空列表表示全部通过。
    """

    valid: bool
    moved: frozenset[str] = field(default_factory=frozenset)
    errors: list[str] = field(default_factory=list)


Assignment = dict[str, Placement]


def valid_start(start: Start, length: int) -> bool:
    """判断起点对于给定长度是否落在 5x8 网格内且不跨天。"""
    return (
        0 <= start.day < DAYS
        and 0 <= start.period < PERIODS
        and start.period + length <= PERIODS
    )


def occupancy(start: Start, length: int) -> tuple[tuple[int, int], ...]:
    """课节占用的 (day, period) 单元序列；调用方需保证起点合法。"""
    return tuple((start.day, start.period + i) for i in range(length))


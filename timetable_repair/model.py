"""课表最小扰动修复库的数据模型。

一周固定 5 天（周一至周五），每天 8 个节次。每个课节持续 1 或 2
个连续节次，不跨天，课节内使用同一间教室。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

DAYS = 5
PERIODS = 8

DAYS_PER_WEEK = DAYS
PERIODS_PER_DAY = PERIODS


@dataclass(frozen=True)
class Start:
    """课节起点：周几（0..4）与起始节次（0..7）。"""

    day: int
    period: int


@dataclass(frozen=True)
class Lesson:
    """一个课节：每周授课一次，持续 duration 个连续节次。

    allowed_starts 与 allowed_rooms 为候选范围，二者可任意组合。
    """

    lesson_id: str
    teacher: str
    klass: str
    duration: int
    allowed_starts: tuple[Start, ...]
    allowed_rooms: tuple[str, ...]


@dataclass(frozen=True)
class Placement:
    """一个课节的具体安排：起点 + 教室。"""

    start: Start
    room: str

    @property
    def day(self) -> int:
        return self.start.day

    @property
    def period(self) -> int:
        return self.start.period


@dataclass(frozen=True)
class Problem:
    """修复问题实例。

    lessons 为全部课节（含旧课与新课）。baseline 只包含旧课的基线
    安排；不在 baseline 中的课节视为新课。locked_ids 为锁定的旧课 ID
    集合，锁定课节必须保持基线安排。
    """

    lessons: tuple[Lesson, ...]
    baseline: dict[str, Placement]
    locked_ids: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class CheckReport:
    """check 的复核结果。"""

    feasible: bool
    moved: frozenset[str] = field(default_factory=frozenset)
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class RepairResult:
    """repair 的结果。

    feasible 为 False 时表示已穷举证明无解，assignment 与 moved 为空。
    """

    feasible: bool
    assignment: dict[str, Placement] = field(default_factory=dict)
    moved: frozenset[str] = field(default_factory=frozenset)
    reason: Optional[str] = None

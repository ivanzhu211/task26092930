"""课表最小扰动修复库（仅依赖 Python 标准库）。"""

from .check import check
from .model import (
    DAYS,
    PERIODS,
    Assignment,
    CheckResult,
    Lesson,
    Placement,
    Problem,
    RepairResult,
    Start,
)
from .repair import repair

__all__ = [
    "DAYS",
    "PERIODS",
    "Start",
    "Lesson",
    "Placement",
    "Problem",
    "RepairResult",
    "CheckResult",
    "Assignment",
    "repair",
    "check",
]

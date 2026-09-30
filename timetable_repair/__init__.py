"""课表最小扰动修复库（仅使用 Python 标准库）。"""

from .checker import check
from .model import (
    CheckReport,
    Lesson,
    Placement,
    Problem,
    RepairResult,
    Start,
)
from .solver import repair

__all__ = [
    "Start",
    "Lesson",
    "Placement",
    "Problem",
    "RepairResult",
    "CheckReport",
    "repair",
    "check",
]

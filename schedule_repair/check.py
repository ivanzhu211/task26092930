"""对外的 check 接口。"""

from __future__ import annotations

from .model import Assignment, CheckResult, Problem
from .validate import check_assignment


def check(problem: Problem, assignment: Assignment) -> CheckResult:
    """独立校验安排，不依赖 repair 给出的移动集合或合法性标志。"""
    if not isinstance(assignment, dict):
        return CheckResult(valid=False, errors=["BAD_ARGUMENT: assignment 必须是 dict"])
    return check_assignment(problem, assignment)

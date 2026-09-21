"""Tasks: accepted recommendations, followed to a measured outcome."""

import uuid

from bsi_core import models as m
from bsi_core.config import get_settings
from fastapi import APIRouter
from sqlalchemy import func, select

from ..deps import TENANT, Ctx, brand_or_404, child_or_404
from ..problems import Problem
from ..schemas import TaskOut, TaskPatch

router = APIRouter(prefix="/brands/{brand_id}", tags=["tasks"])

# What a person may set. Nothing leaves done - a reopened task would make
# its window meaningless - and impact_measured belongs to the worker.
NEXT = {
    "open": {"in_progress", "done"},
    "in_progress": {"open", "done"},
    "done": set(),
    "impact_measured": set(),
}


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(brand_id: uuid.UUID, c: Ctx = TENANT) -> list[m.Task]:
    brand_or_404(c, brand_id)
    return list(
        c.s.scalars(
            select(m.Task)
            .where(m.Task.brand_id == brand_id)
            .order_by(m.Task.created_at.desc(), m.Task.id)
        )
    )


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def patch_task(
    brand_id: uuid.UUID, task_id: uuid.UUID, body: TaskPatch, c: Ctx = TENANT
) -> m.Task:
    task: m.Task = child_or_404(c, m.Task, brand_id, task_id)
    fields = body.model_dump(exclude_unset=True)
    new = fields.pop("status", task.status)
    if new != task.status:
        if new not in NEXT[task.status]:
            raise Problem(
                422, "Illegal status change", f"{task.status} -> {new}"
            )
        if new == "done":
            task.done_at = c.s.scalar(select(func.now()))
            task.window_days = get_settings().impact_window_days
        task.status = new
    for name, value in fields.items():
        setattr(task, name, value)
    return task

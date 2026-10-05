"""Authenticated agenda APIs; all writes use the existing session/CSRF guard."""
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from apps.api.security import require_user
from services.tasks.store import TaskError

router = APIRouter()


def run(fn):
    try:
        return fn()
    except TaskError as exc:
        raise HTTPException(exc.status, exc.detail) from exc


class SnoozeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    minutes: Literal[10, 60] | None = None
    until: str | None = Field(default=None, max_length=64)


class PushKeys(BaseModel):
    model_config = ConfigDict(extra="forbid")
    p256dh: str = Field(min_length=1, max_length=200)
    auth: str = Field(min_length=1, max_length=100)


class SubscriptionIn(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    endpoint: str = Field(min_length=1, max_length=4096)
    expirationTime: float | None = Field(default=None, ge=0)
    keys: PushKeys
    device_label: str = Field(default="", max_length=100)


class UnsubscribeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint: str = Field(min_length=1, max_length=4096)


@router.get("/api/tasks/{task_id}")
def task(task_id: str, request: Request, user=Depends(require_user)):
    return run(lambda: request.app.state.alice.tasks.get(user, task_id))


@router.get("/api/series/{series_id}")
def series(series_id: str, request: Request, user=Depends(require_user)):
    return run(lambda: request.app.state.alice.tasks.series(user, series_id))


@router.post("/api/series/{series_id}/stop")
def stop_series(series_id: str, request: Request, user=Depends(require_user)):
    return run(lambda: request.app.state.alice.tasks.stop_series(user, series_id))


@router.get("/api/summary/daily")
def daily(request: Request, date: date | None = None, user=Depends(require_user)):
    return run(lambda: request.app.state.alice.tasks.daily_summary(user, date))


@router.get("/api/reminders/{reminder_id}")
def reminder(reminder_id: int, request: Request, user=Depends(require_user)):
    return run(lambda: request.app.state.alice.reminders.get(user, reminder_id))


@router.post("/api/reminders/{reminder_id}/snooze")
def snooze(reminder_id: int, body: SnoozeIn, request: Request, user=Depends(require_user)):
    return run(lambda: request.app.state.alice.reminders.snooze(user, reminder_id, **body.model_dump()))


@router.get("/api/push/config")
def push_config(request: Request, user=Depends(require_user)):
    return request.app.state.alice.push.config()


@router.get("/api/push/subscriptions")
def subscriptions(request: Request, user=Depends(require_user)):
    return request.app.state.alice.push.list(user)


@router.post("/api/push/subscriptions", status_code=201)
def subscribe(body: SubscriptionIn, request: Request, user=Depends(require_user)):
    return run(lambda: request.app.state.alice.push.subscribe(user, body.model_dump()))


@router.delete("/api/push/subscriptions")
def unsubscribe(body: UnsubscribeIn, request: Request, user=Depends(require_user)):
    return run(lambda: request.app.state.alice.push.unsubscribe(user, body.endpoint))

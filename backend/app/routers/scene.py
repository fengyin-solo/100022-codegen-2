"""分场大纲接口：维护分场表，覆盖提交分场、审核分场、调整场次等动作。

拍摄难度的评估规则与重算入口也挂在这里；列表和导出共用同一个服务出口，
保证两处拿到的等级标准一致。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.scene import SceneService
from app.services.scene_difficulty import RULE_VERSION, rule_summary

router = APIRouter(prefix="/api/scene", tags=["分场大纲"])

service = SceneService()

LIST_FIELDS = ["场次编号", "所属剧本", "场景地点", "日戏夜戏", "出场人物", "预计时长", "拍摄难度", "分场状态"]
STATUSES = ["待编写", "已编写", "已审核", "已调整"]


class RecalculatePayload(BaseModel):
    """重算入参：默认重算全部未锁定场次；只重试失败场次或指定场次二选一。"""

    only_failed: bool = False
    entry_ids: list[int] | None = Field(default=None, description="只重算指定场次，用于失败重试")


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按场次编号检索"),
    status: str | None = Query(default=None, description="待编写、已编写、已审核、已调整"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按场次编号与状态过滤分场大纲列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/difficulty-rules")
def difficulty_rules() -> dict[str, Any]:
    """当前拍摄难度评估口径：评分因子、时长上限、争议项判定标准与规则版本。"""
    return rule_summary()


@router.post("/recalculate")
def recalculate_difficulty(payload: RecalculatePayload) -> dict[str, Any]:
    """批量重算拍摄难度。

    单场失败不影响其他场次，失败场次会带原因返回，可再次调用只重试失败项；
    已审核场次保持原结果并计入 skipped。
    """
    if payload.only_failed and payload.entry_ids:
        raise HTTPException(status_code=400, detail="只重试失败场次与指定场次不能同时使用")
    return service.recalculate(only_failed=payload.only_failed, entry_ids=payload.entry_ids)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出分场大纲清单：与列表同一个评估出口，并附上规则版本便于对账。"""
    items = service.list_all_for_export()
    return {"module": "scene", "rule_version": RULE_VERSION, "total": len(items), "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条分场表明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"分场表 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条分场表。

    场景地点或预计时长缺失/无法解析、昼夜缺失时不允许保存，响应里说明具体
    原因；预计时长超上限属于争议项，允许保存但会打上「争议待复核」标记。
    """
    entry, message = service.create_entry(payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message="分场表已登记，拍摄难度已按现行规则评估", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条分场表执行提交分场、审核分场、调整场次；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)

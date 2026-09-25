"""分场大纲接口：维护分场表，覆盖提交分场、审核分场、调整场次与难度重算。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult, RecalculatePayload
from app.services.scene import SceneService
from app.services.scene_difficulty import describe_rules

router = APIRouter(prefix="/api/scene", tags=["分场大纲"])

service = SceneService()

LIST_FIELDS = ["场次编号", "所属剧本", "场景地点", "日戏夜戏", "出场人物", "预计时长", "拍摄难度", "难度争议", "分场状态"]
STATUSES = ["待编写", "已编写", "已审核", "已调整"]


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
    """当前生效的难度评估口径：计分规则、时长上限、争议项判定与历史冻结策略。"""
    return describe_rules()


@router.post("/recalculate")
def recalculate_entries(payload: RecalculatePayload) -> dict[str, Any]:
    """按当前规则版本重算难度。

    不传 entry_ids 时重算全部未审核场次；传入时只重算指定场次，
    用于重算中断后只重试失败场次。已审核分场始终跳过、保持原结果。
    """
    return service.recalculate(entry_ids=payload.entry_ids)


@router.get("/export")
def export_entries(
    keyword: str | None = Query(default=None, description="按场次编号检索"),
    status: str | None = Query(default=None, description="待编写、已编写、已审核、已调整"),
) -> dict[str, Any]:
    """导出分场大纲清单：与列表同一过滤口径、同一份难度评估结果，并附规则版本。"""
    items, total = service.list_entries(keyword=keyword, status=status, page=1, size=10000)
    rules = describe_rules()
    return {
        "module": "scene",
        "total": total,
        "items": items,
        "rule_version": rules["rule_version"],
        "rule_note": rules["frozen_policy"],
    }


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条分场表明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"分场表 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条分场表，缺地点或时长等必填项时拒绝保存并说明原因。"""
    entry, errors = service.create_entry(payload.values)
    if errors:
        return ActionResult(ok=False, message="；".join(errors))
    return ActionResult(ok=True, message="分场表已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条分场表执行提交分场、审核分场、调整场次；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)

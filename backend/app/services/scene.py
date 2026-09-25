"""分场大纲业务规则：状态流转、字段校验、难度评估与批量重算都收在这里。"""
from __future__ import annotations

from typing import Any

from app.services.scene_difficulty import RULE_VERSION, evaluate, parse_duration
from app.store import store

MODULE = "scene"
REQUIRED_FIELDS = ["场次编号", "所属剧本", "场景地点", "预计时长"]
ENTRY_FIELDS = ["场次编号", "所属剧本", "场景地点", "日戏夜戏", "出场人物", "预计时长"]
STATUS_ORDER = ["待编写", "已编写", "已审核", "已调整"]
ACTION_RULES = {"提交分场": "已编写", "审核分场": "已审核", "调整场次": "已调整"}
NEGATIVE_ACTIONS = []

# 已审核分场的评估结果冻结，重算一律跳过。
FROZEN_STATUS = "已审核"


class SceneService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("场次编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, [f"缺少必填字段：{'、'.join(missing)}，请补齐后再保存"]
        minutes = parse_duration(values.get("预计时长"))
        if minutes is None:
            return None, ["预计时长需为正数（单位：分钟），例如 30 或 30分钟"]
        entry = {"id": max((int(row.get("id", 0)) for row in store.rows(MODULE)), default=0) + 1}
        entry.update({field: values.get(field) for field in ENTRY_FIELDS})
        entry["预计时长"] = minutes
        entry["status"] = STATUS_ORDER[0]
        entry["分场状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry.update(self._evaluate(entry))
        store.rows(MODULE).append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"分场表 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于分场大纲可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["分场状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"分场表已{action}"

    def recalculate(self, entry_ids: list[int] | None = None) -> dict[str, Any]:
        """按当前规则版本重算难度。

        - 已审核分场保持原结果，一律跳过；
        - 单场失败（如地点、时长缺失）不中断整体，结果逐场返回；
        - 传入 entry_ids 时只重算指定场次，用于中断后只重试失败场次。
        """
        rows = store.rows(MODULE)
        if entry_ids is not None:
            wanted = {int(item) for item in entry_ids}
            known = {int(row.get("id", 0)) for row in rows}
            missing_ids = sorted(wanted - known)
            targets = [row for row in rows if int(row.get("id", 0)) in wanted]
        else:
            missing_ids = []
            targets = list(rows)

        results: list[dict[str, Any]] = []
        for row in targets:
            item: dict[str, Any] = {"id": row.get("id"), "场次编号": row.get("场次编号")}
            if row.get("status") == FROZEN_STATUS:
                item.update(result="已跳过", reason="已审核分场保持原评估结果，不参与重算")
            else:
                failure = self._recalculate_one(row)
                if failure is None:
                    item.update(result="已重算", reason="")
                else:
                    item.update(result="失败", reason=failure)
            results.append(item)
        for entry_id in missing_ids:
            results.append({"id": entry_id, "场次编号": "", "result": "失败", "reason": "分场表不存在或已归档"})

        summary = {
            "total": len(results),
            "recalculated": sum(1 for item in results if item["result"] == "已重算"),
            "skipped": sum(1 for item in results if item["result"] == "已跳过"),
            "failed": sum(1 for item in results if item["result"] == "失败"),
        }
        return {"rule_version": RULE_VERSION, "summary": summary, "results": results}

    def _recalculate_one(self, row: dict[str, Any]) -> str | None:
        """重算单场；返回 None 表示成功，否则为失败原因。"""
        location = str(row.get("场景地点") or "").strip()
        if not location:
            return "场景地点缺失，请先补齐地点再重算"
        minutes = parse_duration(row.get("预计时长"))
        if minutes is None:
            return "预计时长缺失或不是正数（单位：分钟），请先补齐再重算"
        row["预计时长"] = minutes
        row.update(self._evaluate(row))
        return None

    @staticmethod
    def _evaluate(row: dict[str, Any]) -> dict[str, Any]:
        result = evaluate(
            location=str(row.get("场景地点") or ""),
            day_night=str(row.get("日戏夜戏") or ""),
            minutes=float(row["预计时长"]),
        )
        return result.as_fields()

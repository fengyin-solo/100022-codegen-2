"""分场大纲业务规则：状态流转、字段校验、拍摄难度评估与筛选口径都收在这里。

难度评估口径只有一份（``app.services.scene_difficulty``），列表展示、导出与
批量重算都经过 ``_present`` 出口，保证三处标准完全一致。

历史数据保护：执行「审核分场」时把当时算出的难度结果与规则版本冻结在记录上；
此后阈值再怎么调，列表和导出仍读冻结快照，重算也会跳过已冻结场次。显式执行
「调整场次」才解除冻结、按现行规则重评——绝不悄悄改写审核结论。
"""
from __future__ import annotations

from typing import Any

from app.services.scene_difficulty import (
    RULE_VERSION,
    evaluate_difficulty,
)
from app.store import store

MODULE = "scene"
# 地点、时长缺失直接不允许保存；昼夜取值也必填（取值非法会判争议而非静默）。
REQUIRED_FIELDS = ["场次编号", "所属剧本", "场景地点", "日戏夜戏", "预计时长"]
STATUS_ORDER = ["待编写", "已编写", "已审核", "已调整"]
ACTION_RULES = {"提交分场": "已编写", "审核分场": "已审核", "调整场次": "已调整"}
NEGATIVE_ACTIONS = []

FROZEN_STATUS = "已审核"

# 列表展示与导出共用的展示字段（评估派生字段追加在基础字段之后）。
DIFFICULTY_FIELDS = [
    "拍摄难度",
    "难度总分",
    "地点分类",
    "时长分钟",
    "难度争议",
    "争议说明",
    "难度状态",
    "规则版本",
]


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
        page_rows = [self._present(dict(row)) for row in rows[start:start + size]]
        return page_rows, total

    def list_all_for_export(self) -> list[dict[str, Any]]:
        """导出口径：与列表同一个 _present 出口，不允许另搞一套等级标准。"""
        return [self._present(dict(row)) for row in store.rows(MODULE)]

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        return self._present(dict(row)) if row is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """登记分场表。

        地点或时长缺失/无法解析、昼夜缺失时不允许保存，并返回具体原因；
        时长超上限属于争议项而非非法输入，允许保存但会打上争议标记。
        """
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}；地点或时长缺失时不允许保存分场表"

        result = evaluate_difficulty(
            location=values.get("场景地点"),
            day_night=values.get("日戏夜戏"),
            duration=values.get("预计时长"),
        )
        if not result.ok:
            return None, f"分场表未保存：{result.message}"

        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        if str(values.get("出场人物") or "").strip():
            entry["出场人物"] = values.get("出场人物")
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["难度锁定"] = False
        entry.update(self._live_assessment(entry))
        rows.append(entry)
        return self._present(dict(entry)), ""

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"分场表 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于分场大纲可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"

        if action == "审核分场":
            assessment = self._live_assessment(entry)
            if assessment.get("难度状态") == "评估失败":
                return None, (
                    "审核分场前拍摄难度必须可评估："
                    f"{assessment.get('评估原因', '请补全场景地点与预计时长')}"
                )
            self._freeze(entry, assessment)
        elif action == "调整场次":
            # 显式调整是一次新修订：解除冻结并按现行规则重评，过程可追溯。
            self._unfreeze(entry)

        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        if not entry.get("难度锁定"):
            entry.update(self._live_assessment(entry))
        return self._present(dict(entry)), f"分场表已{action}"

    # ---- 拍摄难度评估 -------------------------------------------------

    def _live_assessment(self, entry: dict[str, Any]) -> dict[str, Any]:
        """按当前规则现算一场，不落规则版本以外的口径。"""
        result = evaluate_difficulty(
            location=entry.get("场景地点"),
            day_night=entry.get("日戏夜戏"),
            duration=entry.get("预计时长"),
            manual_dispute=bool(entry.get("人工争议标记")),
        )
        if not result.ok:
            return {
                "拍摄难度": None,
                "难度总分": None,
                "地点分类": None,
                "时长分钟": None,
                "难度争议": False,
                "争议说明": [],
                "难度状态": "评估失败",
                "评估原因": result.message,
                "规则版本": RULE_VERSION,
            }
        snapshot = result.to_snapshot()
        snapshot["难度状态"] = "争议待复核" if result.disputed else "已评估"
        snapshot.pop("评估原因", None)
        return snapshot

    def _freeze(self, entry: dict[str, Any], assessment: dict[str, Any]) -> None:
        """审核时冻结评估快照；之后任何阈值变更都影响不到这条记录。"""
        entry["难度锁定"] = True
        for field in DIFFICULTY_FIELDS:
            if field in assessment:
                entry[field] = assessment[field]
        entry["冻结时规则版本"] = assessment.get("规则版本", RULE_VERSION)

    def _unfreeze(self, entry: dict[str, Any]) -> None:
        entry["难度锁定"] = False
        entry.pop("冻结时规则版本", None)

    def _present(self, entry: dict[str, Any]) -> dict[str, Any]:
        """列表 / 详情 / 导出唯一出口：锁定读快照，未锁定按现行规则现算。"""
        if entry.get("难度锁定"):
            # 读冻结快照，冻结时是什么等级就展示什么，绝不按现行阈值重算。
            for field in DIFFICULTY_FIELDS:
                if field in entry:
                    continue
                entry[field] = None
            entry["规则版本"] = entry.get("冻结时规则版本", entry.get("规则版本"))
            entry.pop("评估原因", None)
            return entry

        entry["难度锁定"] = bool(entry.get("难度锁定", False))
        entry.update(self._live_assessment(entry))
        return entry

    def recalculate(
        self,
        *,
        only_failed: bool = False,
        entry_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """批量重算难度。

        - 默认重算所有未锁定场次，已审核（锁定）场次保持原结果、只计跳过；
        - 单场失败不中断整批，失败场次记录原因，可带 ``only_failed`` 或
          ``entry_ids`` 只重试失败场次；
        - 阈值变更后旧场次只更新评估派生字段，原始填报字段一律不动。
        """
        succeeded: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []

        id_filter = set(entry_ids) if entry_ids else None
        for row in store.rows(MODULE):
            entry_id = int(row.get("id", 0))
            if id_filter is not None and entry_id not in id_filter:
                continue

            if row.get("难度锁定"):
                # 只重试失败场次时，已锁定场既不算失败也不在本次范围里。
                if only_failed:
                    continue
                skipped.append({
                    "id": entry_id,
                    "场次编号": row.get("场次编号"),
                    "原因": "已审核分场难度已锁定，保持原结果不重算",
                })
                continue

            previous_failed = self._present(dict(row)).get("难度状态") == "评估失败"
            if only_failed and not previous_failed:
                continue

            assessment = self._live_assessment(row)
            if assessment.get("难度状态") == "评估失败":
                # 清掉上一次成功时的派生字段，避免列表里残留过期等级。
                for field in ("拍摄难度", "难度总分", "地点分类", "时长分钟"):
                    row[field] = None
                row["难度争议"] = False
                row["争议说明"] = []
                row["难度状态"] = "评估失败"
                row["评估原因"] = assessment.get("评估原因", "")
                failed.append({
                    "id": entry_id,
                    "场次编号": row.get("场次编号"),
                    "原因": row["评估原因"],
                })
                continue

            row.pop("评估原因", None)
            row.update(assessment)
            succeeded.append({
                "id": entry_id,
                "场次编号": row.get("场次编号"),
                "拍摄难度": row.get("拍摄难度"),
                "难度争议": row.get("难度争议"),
            })

        return {
            "rule_version": RULE_VERSION,
            "total": len(succeeded) + len(failed) + len(skipped),
            "succeeded": succeeded,
            "failed": failed,
            "skipped": skipped,
            "ok": not failed,
        }

"""分场拍摄难度评估规则：等级计算、时长上限与争议项判定口径都收在这里。

口径约定：
- 以单个场次为计算单位，依据「场景地点、日戏夜戏、预计时长」三项计分定级；
- 单场预计时长设有上限，超限或命中特殊组合时标记为争议项，需人工确认；
- 阈值调整必须同步升级 RULE_VERSION。列表、导出、重算共用本模块同一份规则，
  已评估记录只保留评估当时的版本，任何阈值变更都不会静默改写历史结果。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# 规则版本：任何阈值/口径调整都必须升版本号，历史记录凭该字段保留当时结果。
RULE_VERSION = "v1.0"

# 难度等级（由低到高）
LEVELS = ["低", "中", "高", "极高"]
LEVEL_SCORE_BANDS = [(0, 2), (2, 4), (4, 6)]  # [低:0~1, 中:2~3, 高:4~5]，>=6 极高

# 预计时长口径，单位：分钟
DURATION_UNIT = "分钟"
DURATION_SCORE_THRESHOLDS = [(20, 1), (40, 2), (60, 3)]  # 超过分钟数 -> 加分
DURATION_MAX_MINUTES = 90  # 单场预计时长上限
RISKY_NIGHT_OUTDOOR_MINUTES = 40  # 夜戏+外景组合的争议阈值

# 场景地点内外景识别关键词（都不命中视为无法判断，记争议）
OUTDOOR_KEYWORDS = ("外景", "街", "路", "山", "林", "海", "河", "湖", "郊", "野", "滩", "桥")
INDOOR_KEYWORDS = ("内景", "摄影棚", "棚内", "室", "厅", "馆", "店", "宅", "办公室", "病房")

# 日戏夜戏可识别取值
DAY_TOKENS = ("日戏", "日", "白天")
NIGHT_TOKENS = ("夜戏", "夜", "夜晚")
DUSK_TOKENS = ("黄昏", "傍晚", "黎明", "清晨")

_DURATION_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(?:分钟?|min)?s?\s*$", re.IGNORECASE)


@dataclass
class DifficultyResult:
    """单场评估结果。"""

    level: str
    score: int
    disputed: bool
    dispute_reasons: list[str] = field(default_factory=list)
    rule_version: str = RULE_VERSION

    def as_fields(self) -> dict[str, Any]:
        """写回分场表记录的字段集合。"""
        return {
            "拍摄难度": self.level,
            "难度评分": self.score,
            "难度争议": self.disputed,
            "争议原因": "；".join(self.dispute_reasons),
            "难度规则版本": self.rule_version,
        }


def parse_duration(value: Any) -> float | None:
    """把预计时长解析成分钟数；无法解析或非正数返回 None。

    接受 30、"30"、"30分钟"、"30min" 等写法。
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        minutes = float(value)
        return minutes if minutes > 0 else None
    match = _DURATION_RE.match(str(value))
    if not match:
        return None
    minutes = float(match.group(1))
    return minutes if minutes > 0 else None


def _classify_location(location: str) -> tuple[str, int]:
    """返回（地点类型, 加分明细）：外景、内景或无法判断。"""
    if any(token in location for token in OUTDOOR_KEYWORDS):
        return "外景", 2
    if any(token in location for token in INDOOR_KEYWORDS):
        return "内景", 0
    return "无法判断", 1


def _classify_day_night(day_night: str) -> tuple[str, int]:
    """返回（时段, 加分明细）：日戏、夜戏、黄昏/清晨或无法识别。"""
    text = day_night.strip()
    if not text:
        return "未填写", 1
    if any(token in text for token in NIGHT_TOKENS):
        return "夜戏", 2
    if any(token in text for token in DUSK_TOKENS):
        return "黄昏/清晨", 1
    if any(token in text for token in DAY_TOKENS):
        return "日戏", 0
    return "无法识别", 1


def _duration_score(minutes: float) -> int:
    """时长计分取所达档位的分值（不累计）：>20 得 1 分、>40 得 2 分、>60 得 3 分。"""
    return max((points for threshold, points in DURATION_SCORE_THRESHOLDS if minutes > threshold), default=0)


def _level_for_score(score: int) -> str:
    if score >= 6:
        return "极高"
    if score >= 4:
        return "高"
    if score >= 2:
        return "中"
    return "低"


def evaluate(*, location: str, day_night: str, minutes: float) -> DifficultyResult:
    """按统一口径计算单场难度。调用方须先确认地点非空、时长为正。"""
    reasons: list[str] = []

    location_kind, location_points = _classify_location(location)
    if location_kind == "无法判断":
        reasons.append("场景地点无法识别内景/外景，需制片部门补注地点类型")

    period, period_points = _classify_day_night(day_night)
    if period in ("无法识别", "未填写"):
        reasons.append("日戏夜戏未按「日戏/夜戏/黄昏/清晨」标注，无法确定灯光与工时口径")

    duration_points = _duration_score(minutes)
    score = location_points + period_points + duration_points

    # 争议口径 1：超过单场时长上限，强制定为极高并转人工确认。
    if minutes > DURATION_MAX_MINUTES:
        level = "极高"
        reasons.append(
            f"预计时长 {minutes:g} 分钟超过单场上限 {DURATION_MAX_MINUTES} 分钟，"
            "需拆分场次或由制片经理确认排期"
        )
    else:
        level = _level_for_score(score)

    # 争议口径 2：夜戏 + 外景 + 长时长的高危组合。
    if location_kind == "外景" and period == "夜戏" and minutes > RISKY_NIGHT_OUTDOOR_MINUTES:
        reasons.append(
            f"夜戏外景且预计时长超过 {RISKY_NIGHT_OUTDOOR_MINUTES} 分钟，"
            "需安全与灯光专项评估"
        )

    return DifficultyResult(level=level, score=score, disputed=bool(reasons), dispute_reasons=reasons)


def describe_rules() -> dict[str, Any]:
    """当前规则的完整口径说明，供前端页面与导出附注使用。"""
    return {
        "rule_version": RULE_VERSION,
        "duration_unit": DURATION_UNIT,
        "duration_max_minutes": DURATION_MAX_MINUTES,
        "levels": LEVELS,
        "score_rules": [
            "场景地点：外景 +2 分，内景 +0 分，无法判断 +1 分并记争议",
            "日戏夜戏：夜戏 +2 分，黄昏/清晨 +1 分，日戏 +0 分，无法识别或未填写 +1 分并记争议",
            f"预计时长：超过 20 分钟 +1 分，超过 40 分钟 +2 分，超过 60 分钟 +3 分",
            "等级映射：0~1 分低，2~3 分中，4~5 分高，6 分及以上极高",
        ],
        "dispute_rules": [
            f"预计时长超过单场上限 {DURATION_MAX_MINUTES} 分钟：强制定为极高，需拆分或制片确认",
            f"夜戏且外景、预计时长超过 {RISKY_NIGHT_OUTDOOR_MINUTES} 分钟：需安全与灯光专项评估",
            "日戏夜戏不在「日戏/夜戏/黄昏/清晨」可识别范围内：需补标后确认",
            "场景地点无法识别为内景或外景：需补注地点类型后确认",
        ],
        "frozen_policy": "已审核分场冻结评估时的规则版本与等级；阈值调整只对未审核场次生效，不回写历史结果。",
    }

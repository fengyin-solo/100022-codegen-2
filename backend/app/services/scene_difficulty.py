"""分场拍摄难度评估规则（单一事实来源）。

分场大纲列表、导出、批量重算都必须走 ``evaluate_difficulty``，保证任何入口
算出来的等级口径一致。

规则版本：阈值任何一次调整都要升版本号。已审核分场会把评估结果连同当时的
规则版本一起冻结（见 scene 服务里的 freeze 逻辑），之后无论这里怎么改阈值，
历史结果都不会被悄悄改写；只有未冻结的分场才按当前规则现算。

评分模型（满分按各因子累加）：
1. 场景地点基础分：棚拍 1 分、常规实景 2 分、特殊外景 3 分；
2. 日戏夜戏：日戏 0 分，夜戏 +1 分；
3. 预计时长：≤90 分钟 0 分；91–180 分钟 +1 分；181–240 分钟 +2 分；
   超过 240 分钟（单场时长上限）+3 分并判争议。
总分 ≤2 低难度，3–4 中难度，≥5 高难度。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# 规则版本：改阈值必须升版本，便于追溯已冻结分场用的是哪套口径。
RULE_VERSION = "2026-09-25-v1"

# 单场预计时长上限（分钟）：超过即判争议项，需要人工复核排期。
DURATION_LIMIT_MINUTES = 240

# 时长分档阈值（分钟，含下界不含上界）与对应加分。
DURATION_BANDS: list[tuple[float, int]] = [
    (90, 0),
    (180, 1),
    (240, 2),
]
DURATION_OVER_LIMIT_SCORE = 3

# 等级分档（总分上限，含）。
GRADE_LIMITS: list[tuple[int, str]] = [
    (2, "低"),
    (4, "中"),
]
GRADE_HIGHEST = "高"

DAY_OPTION = "日戏"
NIGHT_OPTION = "夜戏"
DAY_NIGHT_OPTIONS = [DAY_OPTION, NIGHT_OPTION]
NIGHT_BONUS = 1

# 场景地点分类关键词；按「特殊外景 → 棚拍」顺序优先匹配，都不中按常规实景。
LOCATION_STUDIO_KEYWORDS = ["棚", "摄影棚", "演播室", "置景"]
LOCATION_SPECIAL_KEYWORDS = [
    "高海拔", "高原", "雪山", "雪地", "沙漠", "水下", "潜水",
    "航拍", "高空", "悬崖", "危爆", "爆破", "火场", "森林", "密林",
    "海上", "江面", "激流", "洞穴", "冰川",
]
LOCATION_SCORES = {"棚拍": 1, "常规实景": 2, "特殊外景": 3}

# 争议项判定口径（自动）：超时长上限 / 昼夜无法判定；另有手工标记口径。
DISPUTE_OVER_DURATION = f"预计时长超过单场上限{DURATION_LIMIT_MINUTES}分钟"
DISPUTE_DAY_NIGHT = "日戏夜戏取值无法判定（仅支持日戏/夜戏）"
DISPUTE_MANUAL = "人工标记需复核"


@dataclass
class DifficultyResult:
    """单场评估结果；失败时 ok=False，message 说明原因，可用于重试反馈。"""

    grade: str | None = None
    score: int = 0
    location_category: str | None = None
    duration_minutes: int | None = None
    disputed: bool = False
    dispute_reasons: list[str] = field(default_factory=list)
    rule_version: str | None = None
    ok: bool = True
    message: str = ""

    def to_snapshot(self) -> dict[str, Any]:
        """冻结到分场记录上的快照：等级、依据与规则版本一并留存。"""
        return {
            "拍摄难度": self.grade,
            "难度总分": self.score,
            "地点分类": self.location_category,
            "时长分钟": self.duration_minutes,
            "难度争议": self.disputed,
            "争议说明": list(self.dispute_reasons),
            "规则版本": self.rule_version or RULE_VERSION,
        }


def classify_location(location: str) -> str:
    """按关键词把场景地点归入棚拍 / 特殊外景 / 常规实景。"""
    text = location or ""
    if any(keyword in text for keyword in LOCATION_SPECIAL_KEYWORDS):
        return "特殊外景"
    if any(keyword in text for keyword in LOCATION_STUDIO_KEYWORDS):
        return "棚拍"
    return "常规实景"


def parse_duration_minutes(value: Any) -> tuple[int | None, str | None]:
    """把预计时长解析成分钟。

    接受纯数字（按分钟）或带单位文本：``120分钟``、``2小时``、``1.5h``、
    ``90min``。解析失败返回 None 与可读原因。
    """
    if value is None or str(value).strip() == "":
        return None, "预计时长缺失"
    text = str(value).strip().lower().replace(" ", "")
    unit_minutes = 1
    if text.endswith(("小时", "时")):
        text = text.rsplit("小", 1)[0] if text.endswith("小时") else text[:-1]
        unit_minutes = 60
    elif text.endswith("h"):
        text = text[:-1]
        unit_minutes = 60
    elif text.endswith(("分钟", "分", "min", "m")):
        for suffix in ("分钟", "min", "分", "m"):
            if text.endswith(suffix):
                text = text[: -len(suffix)]
                break
    try:
        number = float(text)
    except ValueError:
        return None, f"预计时长「{value}」无法解析为分钟数"
    if number <= 0:
        return None, f"预计时长「{value}」必须为正数"
    minutes = int(round(number * unit_minutes))
    return minutes, None


def normalize_day_night(value: Any) -> str | None:
    """归一化昼夜取值；无法判定返回 None。"""
    text = str(value or "").strip()
    if "夜" in text:
        return NIGHT_OPTION
    if "日" in text or "昼" in text:
        return DAY_OPTION
    return None


def evaluate_difficulty(
    *,
    location: Any,
    day_night: Any,
    duration: Any,
    manual_dispute: bool = False,
) -> DifficultyResult:
    """按当前规则计算单场拍摄难度。列表、导出、重算共用这一个入口。

    地点或时长缺失/非法时返回失败结果（ok=False）并说明原因；调用方据此
    拒绝保存或把该场标记为重试失败。
    """
    result = DifficultyResult()

    if not str(location or "").strip():
        result.ok = False
        result.message = "场景地点缺失，无法评估拍摄难度"
        return result

    minutes, duration_error = parse_duration_minutes(duration)
    if duration_error:
        result.ok = False
        result.message = duration_error
        return result
    result.duration_minutes = minutes

    category = classify_location(str(location))
    result.location_category = category
    score = LOCATION_SCORES[category]

    normalized = normalize_day_night(day_night)
    if normalized is None:
        result.disputed = True
        result.dispute_reasons.append(DISPUTE_DAY_NIGHT)
    elif normalized == NIGHT_OPTION:
        score += NIGHT_BONUS

    if minutes is not None and minutes > DURATION_LIMIT_MINUTES:
        score += DURATION_OVER_LIMIT_SCORE
        result.disputed = True
        result.dispute_reasons.append(DISPUTE_OVER_DURATION)
    else:
        for upper, band_score in DURATION_BANDS:
            if minutes is not None and minutes <= upper:
                score += band_score
                break
        else:
            score += DURATION_BANDS[-1][1]

    if manual_dispute:
        result.disputed = True
        result.dispute_reasons.append(DISPUTE_MANUAL)

    result.score = score
    for upper, grade in GRADE_LIMITS:
        if score <= upper:
            result.grade = grade
            break
    else:
        result.grade = GRADE_HIGHEST
    result.message = "评估通过"
    return result


def rule_summary() -> dict[str, Any]:
    """规则口径说明，供前端展示与导出附随，避免各方按各自理解解释等级。"""
    return {
        "rule_version": RULE_VERSION,
        "duration_limit_minutes": DURATION_LIMIT_MINUTES,
        "location_scores": LOCATION_SCORES,
        "night_bonus": NIGHT_BONUS,
        "duration_bands": [
            {"max_minutes": upper, "score": score} for upper, score in DURATION_BANDS
        ],
        "duration_over_limit_score": DURATION_OVER_LIMIT_SCORE,
        "grade_limits": [
            {"max_score": upper, "grade": grade} for upper, grade in GRADE_LIMITS
        ],
        "grade_highest": GRADE_HIGHEST,
        "dispute_criteria": [
            DISPUTE_OVER_DURATION,
            DISPUTE_DAY_NIGHT,
            DISPUTE_MANUAL,
        ],
        "day_night_options": DAY_NIGHT_OPTIONS,
    }

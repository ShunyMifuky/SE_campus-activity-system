"""实验三：运行数据分析脚本（可复核）。

用途
----
读取教师提供的模拟运行数据（7 张 CSV），算出一组固定口径的统计量，
输出 metrics.json（给报告引用）与 report_tables.md（人可读的表格）。
报告中出现的每个数字都应能由本脚本复现。

用法
----
    python scripts/analyze_runtime_data.py --data-dir <数据目录> --out-dir <输出目录>

口径约定（重要）
----------------
1. **请求数 ≠ 人数**：registration_log 一行是一次「报名请求」，同一学生
   可能因为重试产生多行；报告里凡说「次」均指请求，说「人」均指去重后的
   student_id，两者不混用。
2. **访问次数 ≠ 浏览人数**：user_behavior 一行是一次页面事件；只对
   student_id 去重后才代表人数。
3. **反馈去重**：feedback.csv 存在大量模板句重复，先按文本去重再归类；
   「频次」只用于说明该说法被重复提交了多少次，不作为独立样本量。
4. **数据来源边界**：这批数据由教师提供、并非本组 V2.0 产生，因此只用于
   「发现问题 / 提出需求」，绝不作为 V3.0 的实测效果。
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------- 基础设施
TS_FORMAT = "%Y-%m-%d %H:%M:%S"


def read_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_ts(value: str):
    value = (value or "").strip()
    return datetime.strptime(value, TS_FORMAT) if value else None


def percentile(values: list[int], ratio: float) -> float:
    """线性插值分位数（样本已排序）。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * ratio
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return round(ordered[low] * (1 - weight) + ordered[high] * weight, 1)


def describe(values: list[int]) -> dict:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "mean": round(statistics.mean(values), 1),
        "p50": percentile(values, 0.50),
        "p90": percentile(values, 0.90),
        "p99": percentile(values, 0.99),
        "max": max(values),
    }


# ---------------------------------------------------------------- 各分析块
def analyze_scale(data: dict) -> dict:
    behaviors = data["behavior"]
    registrations = data["registration"]
    waitlist = data["waitlist"]
    logs = data["system_log"]
    activities = data["activity"]

    all_ts = [
        parse_ts(row["event_ts"]) for row in behaviors if row.get("event_ts")
    ] + [parse_ts(row["request_ts"]) for row in registrations if row.get("request_ts")]

    return {
        "tables": {
            "activity": len(activities),
            "user_behavior": len(behaviors),
            "registration_log": len(registrations),
            "waitlist_log": len(waitlist),
            "feedback": len(data["feedback"]),
            "system_log": len(logs),
        },
        "distinct_students": {
            "behavior": len({r["student_id"] for r in behaviors if r["student_id"]}),
            "registration": len({r["student_id"] for r in registrations if r["student_id"]}),
            "feedback": len({r["student_id"] for r in data["feedback"] if r["student_id"]}),
        },
        "distinct_activities": {
            "declared": len({r["activity_id"] for r in activities if r["activity_id"]}),
            "touched_by_registration": len(
                {r["activity_id"] for r in registrations if r["activity_id"]}
            ),
        },
        "time_span": {
            "start": min(all_ts).strftime(TS_FORMAT) if all_ts else "",
            "end": max(all_ts).strftime(TS_FORMAT) if all_ts else "",
        },
        "capacity": {
            "min": min(int(r["capacity"]) for r in activities),
            "max": max(int(r["capacity"]) for r in activities),
            "median": statistics.median(int(r["capacity"]) for r in activities),
        },
        "category": Counter(r["category"] for r in activities).most_common(),
    }


def analyze_registration(data: dict) -> dict:
    rows = data["registration"]
    applies = [r for r in rows if r["action"] == "apply"]
    results = Counter(r["result"] for r in applies)
    total = len(applies)

    failures = sum(v for k, v in results.items() if k not in ("accepted", "waitlisted"))

    by_activity = []
    per_activity = defaultdict(list)
    for row in applies:
        per_activity[row["activity_id"]].append(row)
    for activity_id, items in per_activity.items():
        counts = Counter(r["result"] for r in items)
        failed = sum(v for k, v in counts.items() if k not in ("accepted", "waitlisted"))
        by_activity.append(
            {
                "activity_id": activity_id,
                "requests": len(items),
                "accepted": counts.get("accepted", 0),
                "waitlisted": counts.get("waitlisted", 0),
                "duplicate": counts.get("duplicate", 0),
                "capacity_conflict": counts.get("capacity_conflict", 0),
                "server_error": counts.get("server_error", 0),
                "failure_rate": round(failed / len(items) * 100, 1),
            }
        )
    by_activity.sort(key=lambda x: (-x["failure_rate"], -x["requests"]))

    return {
        "apply_requests": total,
        "cancel_requests": sum(1 for r in rows if r["action"] == "cancel"),
        "by_result": [
            {"result": k, "count": v, "share_of_apply": round(v / total * 100, 1)}
            for k, v in results.most_common()
        ],
        "failed_requests": failures,
        "failure_rate": round(failures / total * 100, 1),
        "by_activity": by_activity,
        "hour_distribution": Counter(r["request_ts"][11:13] for r in applies).most_common(),
    }


def analyze_duplicate(data: dict) -> dict:
    """重复提交：同一学生对同一活动的连续请求间隔，以及最终是否成功。"""
    rows = [r for r in data["registration"] if r["action"] == "apply"]
    rows.sort(key=lambda r: (r["student_id"], r["activity_id"], r["request_ts"]))

    pairs = defaultdict(list)
    for row in rows:
        pairs[(row["student_id"], row["activity_id"])].append(row)

    duplicate_requests = [r for r in rows if r["result"] == "duplicate"]
    retry_flag = Counter(r["client_retry"] for r in duplicate_requests)

    intervals = []          # 重复请求与上一次请求的间隔（秒）
    resolved = Counter()    # 该 (学生, 活动) 的最终结果
    duplicate_pairs = 0

    for (_student, _activity), items in pairs.items():
        if not any(r["result"] == "duplicate" for r in items):
            continue
        duplicate_pairs += 1
        for index, item in enumerate(items):
            if item["result"] != "duplicate" or index == 0:
                continue
            previous = parse_ts(items[index - 1]["request_ts"])
            current = parse_ts(item["request_ts"])
            if previous and current:
                intervals.append(int((current - previous).total_seconds()))
        # 该对最终的落点：取最后一条非 duplicate 的结果，没有则记 duplicate
        final = next(
            (r["result"] for r in reversed(items) if r["result"] != "duplicate"),
            "duplicate",
        )
        resolved[final] += 1

    affected_students = {r["student_id"] for r in duplicate_requests}
    affected_activities = {r["activity_id"] for r in duplicate_requests}

    return {
        "duplicate_requests": len(duplicate_requests),
        "client_retry_flag": dict(retry_flag),
        "affected_pairs": duplicate_pairs,
        "affected_students": len(affected_students),
        "affected_activities": len(affected_activities),
        "interval_seconds": describe(intervals),
        "short_intervals_10s": sum(1 for v in intervals if v <= 10),
        "final_resolution": resolved.most_common(),
    }


def analyze_latency(data: dict) -> dict:
    rows = [r for r in data["registration"] if r["latency_ms"]]
    all_values = [int(r["latency_ms"]) for r in rows]
    by_result = {}
    for result in ("accepted", "waitlisted", "duplicate", "capacity_conflict", "server_error", "cancelled"):
        values = [int(r["latency_ms"]) for r in rows if r["result"] == result]
        if values:
            by_result[result] = describe(values)
    return {"overall": describe(all_values), "by_result": by_result}


def analyze_waitlist(data: dict) -> dict:
    rows = data["waitlist"]
    transitions = Counter((r["old_status"], r["new_status"]) for r in rows)
    reasons = Counter(r["reason_code"] for r in rows)

    entries = defaultdict(list)
    for row in rows:
        entries[row["application_id"]].append(row)
    for items in entries.values():
        items.sort(key=lambda r: r["change_ts"])

    waits = []              # 从进入候补到被递补的等待时长（小时）
    per_activity = defaultdict(lambda: {"entered": 0, "promoted": 0})
    for application_id, items in entries.items():
        entered_at = next(
            (parse_ts(r["change_ts"]) for r in items if r["new_status"] == "waiting"), None
        )
        promoted = next(
            (r for r in items if r["old_status"] == "waiting" and r["new_status"] == "accepted"),
            None,
        )
        activity_id = items[0]["activity_id"]
        if entered_at is not None:
            per_activity[activity_id]["entered"] += 1
        if promoted is not None:
            per_activity[activity_id]["promoted"] += 1
            if entered_at is not None:
                delta = parse_ts(promoted["change_ts"]) - entered_at
                waits.append(delta.total_seconds() / 3600)

    # 候补结果触达：被递补的人，在递补后 24 小时内有没有访问过状态页
    behavior_by_student = defaultdict(list)
    for row in data["behavior"]:
        behavior_by_student[row["student_id"]].append(row)

    promoted_students = {}
    for application_id, items in entries.items():
        promoted = next(
            (r for r in items if r["old_status"] == "waiting" and r["new_status"] == "accepted"),
            None,
        )
        if promoted:
            promoted_students[promoted["student_id"]] = parse_ts(promoted["change_ts"])

    checked_within_24h = 0
    checked_within_72h = 0
    for student_id, promoted_at in promoted_students.items():
        views = [
            parse_ts(r["event_ts"])
            for r in behavior_by_student.get(student_id, [])
            if r["page"] == "registration_status"
        ]
        if any(0 <= (v - promoted_at).total_seconds() <= 86400 for v in views):
            checked_within_24h += 1
        if any(0 <= (v - promoted_at).total_seconds() <= 259200 for v in views):
            checked_within_72h += 1

    return {
        "transitions": [
            {"from": k[0], "to": k[1], "count": v} for k, v in transitions.most_common()
        ],
        "reasons": dict(reasons),
        "entered_total": transitions.get(("none", "waiting"), 0),
        "promoted_total": transitions.get(("waiting", "accepted"), 0),
        "promotion_rate": round(
            transitions.get(("waiting", "accepted"), 0)
            / max(transitions.get(("none", "waiting"), 1), 1)
            * 100,
            1,
        ),
        "wait_hours": describe([round(v * 10) / 10 for v in waits]),
        "wait_hours_values": [round(v, 1) for v in sorted(waits)],
        "per_activity": [
            {"activity_id": k, **v}
            for k, v in sorted(per_activity.items(), key=lambda kv: -kv[1]["entered"])
        ],
        "promoted_students": len(promoted_students),
        "checked_status_within_24h": checked_within_24h,
        "checked_status_within_72h": checked_within_72h,
    }


def analyze_behavior(data: dict) -> dict:
    rows = data["behavior"]
    page_counts = Counter(r["page"] for r in rows)
    event_counts = Counter(r["event_name"] for r in rows)
    device_counts = Counter(r["device"] for r in rows if r["device"])

    students_by_page = defaultdict(set)
    for row in rows:
        students_by_page[row["page"]].add(row["student_id"])

    # 浏览漏斗：只统计「既看过列表又看过详情」的人数，避免把次数当人数
    list_viewers = students_by_page["activity_list"]
    detail_viewers = students_by_page["activity_detail"]
    both = list_viewers & detail_viewers

    # 列表→详情的点击倍数：每产生一次列表浏览，平均打开多少个详情
    list_views = event_counts.get("list_view", 0)
    detail_views = event_counts.get("detail_view", 0)

    # 候补/审核结果页的访问强度
    status_views = event_counts.get("status_view", 0)
    registration_views = event_counts.get("registration_page_view", 0)

    # 每个会话内的浏览深度：平均打开几个详情页
    session_details = defaultdict(int)
    for row in rows:
        if row["event_name"] == "detail_view":
            session_details[row["session_id"]] += 1
    depth = list(session_details.values())

    return {
        "page_counts": page_counts.most_common(),
        "event_counts": event_counts.most_common(),
        "device_counts": device_counts.most_common(),
        "device_mobile_share": round(
            device_counts.get("mobile", 0) / max(sum(device_counts.values()), 1) * 100, 1
        ),
        "distinct_students_by_page": {k: len(v) for k, v in students_by_page.items()},
        "list_detail": {
            "list_views": list_views,
            "detail_views": detail_views,
            "detail_per_list": round(detail_views / max(list_views, 1), 2),
            "list_viewers": len(list_viewers),
            "detail_viewers": len(detail_viewers),
            "viewed_both": len(both),
        },
        "status_page": {
            "status_views": status_views,
            "share_of_all_events": round(status_views / max(len(rows), 1) * 100, 1),
            "registration_page_views": registration_views,
        },
        "session_detail_depth": describe(depth),
    }


# 反馈主题的判定规则（写在代码里，保证可复核、可修改）
FEEDBACK_THEMES = [
    (
        "候选结果不可感知",
        ["候补", "排队", "错过", "状态", "变化", "改成成功", "转为成功"],
    ),
    (
        "报名结果不确定 / 失败原因不清",
        ["没有弄清楚原因", "有没有提交成功", "是否成功", "卡住", "难理解", "失败了", "连续点"],
    ),
    (
        "列表信息不足 / 缺少筛选",
        ["标题看着差不多", "逐个看", "一条条打开", "想找周末", "只想参加一类", "查起来有点费时间", "翻了几轮"],
    ),
    (
        "活动信息完整性",
        ["地点说明", "海报里的文字", "时间冲突"],
    ),
    (
        "正向反馈",
        ["比较顺利", "基本都能查到", "比较方便", "还可以", "很顺畅", "比较齐全", "组织得不错"],
    ),
]


def classify_feedback(text: str) -> str:
    for theme, keywords in FEEDBACK_THEMES:
        if any(keyword in text for keyword in keywords):
            return theme
    return "其他"


def analyze_feedback(data: dict) -> dict:
    rows = data["feedback"]
    counter = Counter(r["feedback_text"] for r in rows)

    templates = []
    for text, count in counter.most_common():
        templates.append(
            {"text": text, "count": count, "theme": classify_feedback(text)}
        )

    theme_by_records = Counter()
    theme_by_templates = Counter()
    for item in templates:
        theme_by_records[item["theme"]] += item["count"]
        theme_by_templates[item["theme"]] += 1

    return {
        "records": len(rows),
        "unique_templates": len(counter),
        "duplication_factor": round(len(rows) / max(len(counter), 1), 1),
        "templates": templates,
        "theme_by_records": theme_by_records.most_common(),
        "theme_by_templates": theme_by_templates.most_common(),
    }


def analyze_logs(data: dict) -> dict:
    rows = data["system_log"]
    errors = [r for r in rows if r["level"] == "ERROR"]
    slow = [r for r in rows if r["event_code"] == "SLOW_REQUEST"]

    error_request_ids = {r["request_id"] for r in errors if r["request_id"]}
    # 出错的请求最终在 registration_log 里是什么结果
    by_request = {r["request_id"]: r for r in data["registration"]}
    error_outcomes = Counter(
        by_request[rid]["result"] for rid in error_request_ids if rid in by_request
    )

    return {
        "level_counts": Counter(r["level"] for r in rows).most_common(),
        "component_counts": Counter(r["component"] for r in rows).most_common(),
        "event_code_counts": Counter(r["event_code"] for r in rows).most_common(),
        "error_total": len(errors),
        "error_codes": Counter(r["event_code"] for r in errors).most_common(),
        "error_outcomes": error_outcomes.most_common(),
        "slow_request": {
            "count": len(slow),
            "elapsed": describe([int(r["elapsed_ms"]) for r in slow if r["elapsed_ms"]]),
            "top_activities": Counter(r["activity_id"] for r in slow if r["activity_id"]).most_common(5),
        },
    }


# ---------------------------------------------------------------- 输出
def to_markdown(metrics: dict) -> str:
    lines: list[str] = []
    add = lines.append

    scale = metrics["scale"]
    add("# 运行数据分析结果\n")
    add("> 本文件由 `scripts/analyze_runtime_data.py` 生成，报告中引用的数字均出自此处。\n")

    add("## 1. 数据规模\n")
    add("| 表 | 行数 |\n|---|---:|")
    for name, count in scale["tables"].items():
        add(f"| {name} | {count} |")
    add("")
    add(f"- 时间范围：{scale['time_span']['start']} ~ {scale['time_span']['end']}")
    add(f"- 活动数：{scale['distinct_activities']['declared']}")
    add(f"- 去重学生数（行为表）：{scale['distinct_students']['behavior']}")
    add("")

    reg = metrics["registration"]
    add("## 2. 报名请求结果\n")
    add("| 结果 | 次数 | 占报名请求 |\n|---|---:|---:|")
    for item in reg["by_result"]:
        add(f"| {item['result']} | {item['count']} | {item['share_of_apply']}% |")
    add("")
    add(f"- 报名请求合计：{reg['apply_requests']} 次")
    add(f"- 失败请求（duplicate + capacity_conflict + server_error）：{reg['failed_requests']} 次，占 {reg['failure_rate']}%")
    add("")

    add("## 3. 重复提交\n")
    dup = metrics["duplicate"]
    add(f"- duplicate 请求：{dup['duplicate_requests']} 次；client_retry=1 的请求：{dup['client_retry_flag'].get('1', 0)} 次")
    add(f"- 涉及 (学生, 活动) 组合：{dup['affected_pairs']} 对；学生 {dup['affected_students']} 人；活动 {dup['affected_activities']} 个")
    add(f"- 与上一次请求的间隔：中位数 {dup['interval_seconds'].get('p50')} 秒，≤10 秒的有 {dup['short_intervals_10s']} 次")
    add(f"- 这些组合的最终落点：{dup['final_resolution']}")
    add("")

    add("## 4. 耗时\n")
    lat = metrics["latency"]["overall"]
    add(f"- 全部请求：P50 {lat['p50']}ms / P90 {lat['p90']}ms / P99 {lat['p99']}ms / 最大 {lat['max']}ms")
    add("")
    add("| 结果 | 样本 | 均值 | P50 | P90 |\n|---|---:|---:|---:|---:|")
    for result, item in metrics["latency"]["by_result"].items():
        add(f"| {result} | {item['n']} | {item['mean']}ms | {item['p50']}ms | {item['p90']}ms |")
    add("")

    wl = metrics["waitlist"]
    add("## 5. 候补链路\n")
    add(f"- 进入候补：{wl['entered_total']} 次；被递补：{wl['promoted_total']} 次；递补率 {wl['promotion_rate']}%")
    add(f"- 等待时长（小时）：中位数 {wl['wait_hours'].get('p50')}，P90 {wl['wait_hours'].get('p90')}，最长 {wl['wait_hours'].get('max')}")
    add(f"- 被递补的 {wl['promoted_students']} 人中，24 小时内访问过状态页的 {wl['checked_status_within_24h']} 人；72 小时内 {wl['checked_status_within_72h']} 人")
    add("")

    be = metrics["behavior"]
    add("## 6. 浏览行为\n")
    add("| 页面 | 事件数 | 去重人数 |\n|---|---:|---:|")
    for page, count in be["page_counts"]:
        add(f"| {page} | {count} | {be['distinct_students_by_page'].get(page, 0)} |")
    add("")
    add(f"- 列表浏览 {be['list_detail']['list_views']} 次，详情浏览 {be['list_detail']['detail_views']} 次，比值 {be['list_detail']['detail_per_list']}")
    add(f"- 状态页访问 {be['status_page']['status_views']} 次，占全部行为事件的 {be['status_page']['share_of_all_events']}%")
    add(f"- 移动端事件占比 {be['device_mobile_share']}%")
    add("")

    fb = metrics["feedback"]
    add("## 7. 反馈主题\n")
    add(f"- 反馈 {fb['records']} 条，去重后 {fb['unique_templates']} 种说法（平均每种重复 {fb['duplication_factor']} 次）")
    add("")
    add("| 主题 | 说法数 | 提交次数 |\n|---|---:|---:|")
    template_counts = dict(fb["theme_by_templates"])
    for theme, count in fb["theme_by_records"]:
        add(f"| {theme} | {template_counts.get(theme, 0)} | {count} |")
    add("")

    lg = metrics["logs"]
    add("## 8. 系统日志\n")
    add(f"- 日志 {sum(v for _, v in lg['level_counts'])} 条，ERROR {lg['error_total']} 条：{lg['error_codes']}")
    add(f"- 出错请求在报名表中的最终结果：{lg['error_outcomes']}")
    add(f"- SLOW_REQUEST {lg['slow_request']['count']} 条，中位耗时 {lg['slow_request']['elapsed'].get('p50')}ms")
    add("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="分析实验三模拟运行数据")
    parser.add_argument("--data-dir", required=True, help="包含 7 个 CSV 的目录")
    parser.add_argument("--out-dir", required=True, help="输出目录")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    data = {
        "activity": read_rows(data_dir / "activity.csv"),
        "behavior": read_rows(data_dir / "user_behavior.csv"),
        "registration": read_rows(data_dir / "registration_log.csv"),
        "waitlist": read_rows(data_dir / "waitlist_log.csv"),
        "feedback": read_rows(data_dir / "feedback.csv"),
        "system_log": read_rows(data_dir / "system_log.csv"),
    }

    metrics = {
        "scale": analyze_scale(data),
        "registration": analyze_registration(data),
        "duplicate": analyze_duplicate(data),
        "latency": analyze_latency(data),
        "waitlist": analyze_waitlist(data),
        "behavior": analyze_behavior(data),
        "feedback": analyze_feedback(data),
        "logs": analyze_logs(data),
    }

    (out_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "report_tables.md").write_text(to_markdown(metrics), encoding="utf-8")
    print(f"已输出 {out_dir / 'metrics.json'}")
    print(f"已输出 {out_dir / 'report_tables.md'}")


if __name__ == "__main__":
    main()

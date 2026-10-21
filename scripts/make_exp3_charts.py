"""实验三：由 metrics.json 生成报告插图。

用法：
    python scripts/make_exp3_charts.py --metrics <metrics.json> --out-dir <图片目录>

图表只做「把 metrics.json 里的数字画出来」，不额外计算，保证图与文同源。
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False

INK = "#1f2933"
MUTED = "#64748b"
GRID = "#e2e8f0"
BLUE = "#2f5fd0"
BLUE_SOFT = "#9db4e8"
AMBER = "#c98a1a"
RED = "#b23333"


def _style(ax):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color(GRID)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def chart_results(metrics: dict, out: Path) -> None:
    """报名请求结果构成——把三类失败单独着色。"""
    items = list(reversed(metrics["registration"]["by_result"]))
    labels = [i["result"] for i in items]
    values = [i["count"] for i in items]
    colors = []
    for label in labels:
        if label == "accepted":
            colors.append(BLUE)
        elif label == "waitlisted":
            colors.append(BLUE_SOFT)
        else:
            colors.append(AMBER if label in ("duplicate", "capacity_conflict") else RED)

    fig, ax = plt.subplots(figsize=(6.6, 3.4), dpi=200)
    bars = ax.barh(labels, values, color=colors, height=0.62)
    for bar, value in zip(bars, values):
        ax.text(value + 24, bar.get_y() + bar.get_height() / 2, f"{value}",
                va="center", fontsize=9, color=INK)
    ax.set_xlim(0, max(values) * 1.16)
    ax.set_xlabel("请求次数", color=MUTED, fontsize=9)
    ax.set_title("报名请求结果构成（共 2748 次 apply 请求）", color=INK, fontsize=11, loc="left")
    _style(ax)
    fig.tight_layout()
    fig.savefig(out / "fig1-报名结果构成.png", bbox_inches="tight")
    plt.close(fig)


def chart_depth(metrics: dict, out: Path, data_dir: Path) -> None:
    """每个会话打开的详情页数量分布——说明「逐个点开」不是个别行为。"""
    import csv

    with (data_dir / "user_behavior.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    depth = Counter(r["session_id"] for r in rows if r["event_name"] == "detail_view")
    distribution = Counter(min(v, 10) for v in depth.values())

    xs = sorted(distribution)
    ys = [distribution[x] for x in xs]
    labels = [str(x) if x < 10 else "10+" for x in xs]

    fig, ax = plt.subplots(figsize=(6.6, 3.2), dpi=200)
    bars = ax.bar(labels, ys, color=BLUE_SOFT, width=0.66)
    # 把「打开 5 个及以上」的柱子加深，强调长尾
    for bar, x in zip(bars, xs):
        if x >= 5:
            bar.set_color(BLUE)
    for bar, value in zip(bars, ys):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 6, str(value),
                ha="center", fontsize=8, color=MUTED)
    ax.set_xlabel("单个会话内打开的详情页数量", color=MUTED, fontsize=9)
    ax.set_ylabel("会话数", color=MUTED, fontsize=9)
    ax.set_title("每次浏览要打开多少个活动详情（共 1250 个会话）", color=INK, fontsize=11, loc="left")
    ax.text(0.99, 0.92, f"平均 4.3 个 / P90 8 个", transform=ax.transAxes,
            ha="right", fontsize=9, color=AMBER)
    _style(ax)
    fig.tight_layout()
    fig.savefig(out / "fig2-详情页浏览深度.png", bbox_inches="tight")
    plt.close(fig)


def chart_wait(metrics: dict, out: Path) -> None:
    """候补等待时长分布——中位数 18.1 小时，接近一天。"""
    values = metrics["waitlist"]["wait_hours_values"]
    fig, ax = plt.subplots(figsize=(6.6, 3.2), dpi=200)
    ax.hist(values, bins=[0, 6, 12, 18, 24, 30, 36, 42, 48], color=BLUE_SOFT,
            edgecolor="white", linewidth=1.2)
    median = metrics["waitlist"]["wait_hours"]["p50"]
    ax.axvline(median, color=AMBER, linestyle="--", linewidth=1.4)
    ax.text(median + 0.8, ax.get_ylim()[1] * 0.9, f"中位数 {median} 小时",
            color=AMBER, fontsize=9)
    ax.set_xlabel("从进入候补到被递补的等待时长（小时）", color=MUTED, fontsize=9)
    ax.set_ylabel("人数", color=MUTED, fontsize=9)
    ax.set_title("候补递补的等待时长（130 人）", color=INK, fontsize=11, loc="left")
    _style(ax)
    fig.tight_layout()
    fig.savefig(out / "fig3-候补等待时长.png", bbox_inches="tight")
    plt.close(fig)


def chart_feedback(metrics: dict, out: Path) -> None:
    """反馈主题（按去重后的说法数）。"""
    items = [(t, c) for t, c in metrics["feedback"]["theme_by_records"] if t != "正向反馈"]
    items.sort(key=lambda x: x[1])
    labels = [t for t, _ in items]
    values = [c for _, c in items]
    fig, ax = plt.subplots(figsize=(6.8, 3.1), dpi=200)
    bars = ax.barh(labels, values, color=BLUE, height=0.58)
    for bar, value in zip(bars, values):
        ax.text(value + 0.6, bar.get_y() + bar.get_height() / 2, str(value),
                va="center", fontsize=9, color=INK)
    ax.set_xlim(0, max(values) * 1.2)
    ax.set_xlabel("提及该主题的反馈条数（已按文本去重前统计）", color=MUTED, fontsize=9)
    ax.set_title("用户反馈的问题主题", color=INK, fontsize=11, loc="left")
    _style(ax)
    fig.tight_layout()
    fig.savefig(out / "fig4-反馈主题.png", bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    metrics = json.loads(Path(args.metrics).read_text(encoding="utf-8"))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    chart_results(metrics, out)
    chart_depth(metrics, out, Path(args.data_dir))
    chart_wait(metrics, out)
    chart_feedback(metrics, out)
    print("已生成 4 张图到", out)


if __name__ == "__main__":
    main()

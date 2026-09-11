"""生成实验报告需要插入的设计图。

这是开发辅助脚本，不属于 V1.0 运行时依赖。
实现方式：先写成 SVG，再用 Playwright 驱动本机 Chrome 渲染成 PNG。
（不依赖 matplotlib / cairosvg，避免额外的图形库安装问题。）

使用前需要：pip install playwright，且本机已安装 Chrome
用法：python scripts/make_diagrams.py
输出：docs/diagrams/*.html（矢量源文件）与 docs/diagrams/*.png（报告用图）
"""

from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "diagrams"

FONT = "Microsoft YaHei, SimHei, sans-serif"

# 与网页样式一致的配色
INK = "#1f2933"
MUTED = "#64748b"
FAINT = "#94a3b8"
LINE = "#8a94a0"
BLUE = ("#eef3fd", "#2f5fd0", "#0c2d6b")
TEAL = ("#e9f6ef", "#1f7a4d", "#0d4a2f")
AMBER = ("#fdf4e3", "#9a6206", "#633806")
GRAYB = ("#f1f5f9", "#94a3b8", "#334155")
CORAL = ("#fdeeee", "#b23333", "#7a2222")


def rect(x, y, w, h, fill, stroke, rx=8, lw=1.2):
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="{lw}"/>'
    )


def txt(x, y, s, size=13, fill=INK, anchor="middle", weight="400"):
    return (
        f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" '
        f'text-anchor="{anchor}" font-weight="{weight}" '
        f'dominant-baseline="middle" font-family="{FONT}">{s}</text>'
    )


def node(x, y, w, h, title, lines=(), palette=BLUE, ts=14, ls=12, rx=9):
    fc, ec, tc = palette
    out = [rect(x, y, w, h, fc, ec, rx=rx)]
    cx = x + w / 2
    if title:
        out.append(txt(cx, y + 26, title, size=ts, fill=tc, weight="500"))
    for i, line in enumerate(lines):
        out.append(txt(cx, y + 52 + i * 22, line, size=ls, fill="#4a5560"))
    return out


def diamond(cx, cy, w, h, label, palette=AMBER, size=13):
    fc, ec, tc = palette
    pts = f"{cx},{cy - h / 2} {cx + w / 2},{cy} {cx},{cy + h / 2} {cx - w / 2},{cy}"
    return [
        f'<polygon points="{pts}" fill="{fc}" stroke="{ec}" stroke-width="1.2"/>',
        txt(cx, cy, label, size=size, fill=tc),
    ]


def arrow(x1, y1, x2, y2, color=LINE):
    return (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" '
        f'stroke-width="1.3" marker-end="url(#arrow)"/>'
    )


def polyline(points, color=LINE):
    path = " ".join(f"{x},{y}" for x, y in points)
    return (
        f'<polyline points="{path}" fill="none" stroke="{color}" '
        f'stroke-width="1.3" marker-end="url(#arrow)"/>'
    )


def caption(x, y, s, size=12, fill=MUTED, anchor="start"):
    return txt(x, y, s, size=size, fill=fill, anchor=anchor)


DEFS = f"""<defs>
<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7"
        orient="auto-start-reverse">
  <path d="M1 1 L9 5 L1 9" fill="none" stroke="{LINE}" stroke-width="1.4"
        stroke-linecap="round" stroke-linejoin="round"/>
</marker>
</defs>"""


def svg(width, height, body):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>'
        f"{DEFS}{''.join(body)}</svg>"
    )


# ------------------------------------------------------------ 4.1 系统结构图
def architecture():
    W, H = 800, 612
    b = []

    b.append(rect(250, 20, 300, 52, GRAYB[0], GRAYB[1], rx=9))
    b.append(txt(400, 38, "浏览器", size=14, fill=GRAYB[2], weight="500"))
    b.append(txt(400, 58, "学生 / 活动组织教师 / 访客", size=12, fill="#4a5560"))

    b.append(arrow(400, 72, 400, 96))

    b += node(140, 96, 520, 64, "表示层　Jinja2 模板 + 原生 CSS",
              ("只负责渲染与收集输入，不写任何业务规则",), BLUE, ts=14, ls=12)

    b.append(arrow(400, 160, 400, 188))

    # 业务层容器
    b.append(rect(40, 188, 720, 220, "#f7f9fc", "#c3cfdd", rx=14, lw=1.2))
    b.append(txt(64, 214, "业务层　业务规则的唯一落点", size=14, fill="#1f3f7a",
                 anchor="start", weight="500"))
    b += node(64, 238, 208, 146, "权限装饰器",
              ("角色校验", "资源归属校验"), TEAL, ts=13, ls=12)
    b += node(296, 238, 208, 146, "activity_service",
              ("活动字段校验", "时间先后关系", "人数上限约束", "软下架"), TEAL, ts=13, ls=12)
    b += node(528, 238, 208, 146, "registration_service",
              ("截止时间校验", "名额校验", "重复报名校验"), TEAL, ts=13, ls=12)

    b.append(arrow(400, 408, 400, 436))

    # 数据层容器
    b.append(rect(40, 436, 720, 152, "#f7f9fc", "#c3cfdd", rx=14, lw=1.2))
    b.append(txt(64, 462, "数据层", size=14, fill="#1f3f7a", anchor="start", weight="500"))
    b += node(64, 486, 470, 82, "SQLAlchemy 模型",
              ("users · categories · activities", "registrations · operation_logs"),
              GRAYB, ts=13, ls=12)
    b += node(566, 486, 172, 82, "SQLite",
              ("单文件数据库", "instance/campus.db"), GRAYB, ts=13, ls=11)

    return W, H, b


# ------------------------------------------------------------ 4.2 报名核心流程
def signup_flow():
    W, H = 760, 730
    cx, dw, dh = 230, 264, 74
    rx, rw, rh = 490, 250, 52
    centers = [118, 203, 288, 373, 458]
    questions = [
        "已登录且角色为学生？",
        "活动未被下架？",
        "当前时间未过报名截止？",
        "名额未满？",
        "未重复报名？",
    ]
    branches = ["否", "是", "是", "是", "是"]
    rejects = [
        "未登录 → 跳转登录页\n教师账号 → 403",
        "拒绝：活动已下架",
        "拒绝：报名已截止",
        "拒绝：名额已满",
        "拒绝：请勿重复报名",
    ]

    b = []
    b += node(150, 26, 160, 44, "学生提交报名", (), BLUE, ts=13)
    b.append(arrow(cx, 70, cx, centers[0] - dh / 2))

    for index, cy in enumerate(centers):
        b += diamond(cx, cy, dw, dh, questions[index])
        b.append(arrow(cx + dw / 2, cy, rx, cy, color="#c9903f"))
        b.append(caption((cx + dw / 2 + rx) / 2, cy - 10, branches[index],
                         size=11, fill="#9a6206", anchor="middle"))
        reject_lines = rejects[index].split("\n")
        b.append(rect(rx, cy - rh / 2, rw, rh, CORAL[0], "#e0a3a3", rx=8))
        for line_index, line in enumerate(reject_lines):
            offset = (len(reject_lines) - 1) * 11
            b.append(txt(rx + rw / 2, cy - offset + line_index * 22, line,
                         size=12, fill=CORAL[2]))
        if index < len(centers) - 1:
            b.append(arrow(cx, cy + dh / 2, cx, centers[index + 1] - dh / 2))

    last = centers[-1]
    b.append(arrow(cx, last + dh / 2, cx, 520))
    b += node(150, 520, 160, 44, "写入报名记录", (), TEAL, ts=13)
    b.append(arrow(cx, 564, cx, 584))
    b += node(140, 584, 180, 58, "报名成功",
              ("「我的报名」可见，报名人数 +1",), TEAL, ts=13, ls=11)
    b.append(arrow(cx, 642, cx, 662))
    b += node(120, 662, 220, 44, "可随时取消报名，名额释放", (), GRAYB, ts=13)

    b.append(caption(40, 716, "以上 5 项校验全部在 registration_service 中实现，"
                              "即使绕过页面直接提交请求也会被拒绝。", size=11, fill=FAINT))
    return W, H, b


# ------------------------------------------------------------ 4.3 数据关系图
def er_diagram():
    W, H = 900, 640
    b = []

    def entity(x, y, w, h, title, fields, palette, tag=None, tag_fill=None):
        b.append(rect(x, y, w, h, palette[0], palette[1], rx=9, lw=1.2))
        b.append(txt(x + w / 2, y + 24, title, size=13, fill=palette[2], weight="500"))
        for index, field in enumerate(fields):
            b.append(txt(x + 14, y + 50 + index * 21, field, size=11.5,
                         fill="#44505e", anchor="start"))
        if tag:
            b.append(txt(x + w / 2, y + h - 14, tag, size=11,
                         fill=tag_fill or palette[1]))

    b.append(polyline([(280, 120), (230, 300)]))
    b.append(caption(272, 208, "1 : N　归类", size=11, anchor="start"))
    b.append(polyline([(460, 210), (330, 300)]))
    b.append(caption(376, 246, "1 : N　发布", size=11, anchor="start"))
    b.append(polyline([(420, 420), (620, 270)]))
    b.append(caption(470, 330, "1 : N　被报名", size=11, anchor="start"))
    b.append(polyline([(585, 150), (620, 230)]))
    b.append(caption(596, 182, "1 : N　报名", size=11, anchor="start"))
    b.append(polyline([(520, 210), (745, 300), (745, 420)]))
    b.append(caption(700, 300, "1 : N　操作", size=11, anchor="start"))

    entity(30, 30, 250, 140, "categories　活动分类",
           ["id　PK", "name　UK　（分类名称）", "sort_order　（排序）"], BLUE, tag="REQ-04")

    entity(335, 30, 250, 180, "users　用户",
           ["id　PK　　　　username　UK", "password_hash　（仅存哈希）",
            "real_name　　　student_no", "role　student / teacher", "created_at"],
           BLUE, tag="REQ-01")

    entity(170, 300, 250, 240, "activities　活动",
           ["id　PK　　　　　title", "summary　　　　　location",
            "start_time / end_time", "signup_deadline",
            "capacity　（0 = 不限）", "category_id　FK",
            "creator_id　FK", "canceled_at　（非空即下架）"],
           TEAL, tag="REQ-03 / REQ-04")

    entity(620, 180, 250, 180, "registrations　报名记录",
           ["id　PK", "activity_id　FK", "user_id　FK", "created_at",
            "(activity_id, user_id)　UK"],
           AMBER, tag="REQ-05 / REQ-06", tag_fill="#9a6206")

    entity(620, 420, 250, 180, "operation_logs　操作日志",
           ["id　PK", "actor_id　FK", "action　target_type",
            "target_id　detail", "created_at"],
           GRAYB)

    return W, H, b


DIAGRAMS = {
    "diagram-architecture": architecture,
    "diagram-signup-flow": signup_flow,
    "diagram-er": er_diagram,
}


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)

        for name, builder in DIAGRAMS.items():
            width, height, body = builder()
            markup = svg(width, height, body)

            html = (
                "<!DOCTYPE html><html><head><meta charset='utf-8'>"
                "<style>html,body{margin:0;padding:0;background:#fff}</style>"
                f"</head><body>{markup}</body></html>"
            )
            (OUT_DIR / f"{name}.html").write_text(html, encoding="utf-8")

            page = browser.new_page(
                viewport={"width": width, "height": height}, device_scale_factor=2
            )
            page.goto((OUT_DIR / f"{name}.html").as_uri())
            page.screenshot(path=str(OUT_DIR / f"{name}.png"), full_page=True)
            page.close()

            print(f"  已生成 {name}.png  ({width}x{height})")

        browser.close()

    print(f"\n输出目录：{OUT_DIR}")


if __name__ == "__main__":
    main()

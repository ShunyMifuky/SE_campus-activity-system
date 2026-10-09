"""打包交付：生成项目压缩包与源代码汇编。

用法：python pack_source.py
输出（桌面）：
  校园活动管理系统_V2.0_源代码.zip        —— 含 .git，可完整还原版本记录
  校园活动管理系统_V2.0_源代码汇编.md     —— 便于阅读/打印的源代码清单
"""

import subprocess
import sys
import zipfile
from pathlib import Path

PROJECT = Path("C:/Users/42469/WorkBuddy/2026-09-11-16-51-20/campus-activity-system")
DESKTOP = Path("C:/Users/42469/Desktop")
ZIP_PATH = DESKTOP / "校园活动管理系统_V2.0_源代码.zip"
DOC_PATH = DESKTOP / "校园活动管理系统_V2.0_源代码汇编.md"

EXCLUDE_DIRS = {"__pycache__", ".venv", "venv", "instance", ".pytest_cache"}

# 汇编中的展示顺序（根配置 → 应用骨架 → 数据与规则 → 各模块 → 模板 → 样式 → 测试与脚本）
ORDER = [
    "requirements.txt",
    "requirements-dev.txt",
    "config.py",
    "run.py",
    ".gitignore",
    "app/__init__.py",
    "app/extensions.py",
    "app/models.py",
    "app/decorators.py",
    "app/seed.py",
    "app/services/__init__.py",
    "app/services/activity_service.py",
    "app/services/registration_service.py",
    "app/auth/__init__.py",
    "app/auth/routes.py",
    "app/activities/__init__.py",
    "app/activities/routes.py",
    "app/registrations/__init__.py",
    "app/registrations/routes.py",
    "app/admin/__init__.py",
    "app/admin/routes.py",
    "app/main/__init__.py",
    "app/main/routes.py",
    "app/templates/base.html",
    "app/templates/auth/login.html",
    "app/templates/auth/register.html",
    "app/templates/activities/list.html",
    "app/templates/activities/_card.html",
    "app/templates/activities/detail.html",
    "app/templates/activities/_signup_panel.html",
    "app/templates/activities/form.html",
    "app/templates/activities/mine.html",
    "app/templates/registrations/mine.html",
    "app/templates/registrations/roster.html",
    "app/templates/admin/users.html",
    "app/templates/admin/activities.html",
    "app/templates/errors/403.html",
    "app/templates/errors/404.html",
    "app/static/css/style.css",
    "tests/__init__.py",
    "tests/test_business.py",
    "tests/test_v2.py",
    "scripts/make_diagrams.py",
    "scripts/capture_screenshots.py",
]

LANG = {
    ".py": "python", ".html": "html", ".css": "css",
    ".md": "markdown", ".txt": "text",
}


def iter_project_files():
    """压缩包用的文件遍历：保留 .git（版本记录是交付证据），排除缓存与运行期产物。"""
    for path in sorted(PROJECT.rglob("*")):
        if path.is_dir():
            continue
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        yield path


def iter_source_files():
    """源代码遍历：额外排除 .git 与设计文档，只留源码本身。"""
    for path in iter_project_files():
        parts = path.relative_to(PROJECT).parts
        if ".git" in parts or parts[0] == "docs":
            continue
        yield path


def build_zip():
    count = 0
    total = 0
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in iter_project_files():
            # 压缩包内保留顶层的项目目录名
            arcname = Path("campus-activity-system") / path.relative_to(PROJECT)
            archive.write(path, arcname)
            count += 1
            total += path.stat().st_size
    return count, total


def git(*args):
    result = subprocess.run(["git", *args], cwd=PROJECT, capture_output=True, text=True,
                            encoding="utf-8")
    return (result.stdout or "").strip()


def build_source_doc():
    lines = []
    add = lines.append

    add("# 校园活动管理系统 V2.0 · 源代码汇编\n")
    add("> 实验一 · 基于工程意图的软件迭代开发（V1.0）")
    add("> 实验二 · 基于用户访谈的需求演化（V2.0）　|　小组：林翔宇、王泰然、唐佳涵")
    add("> 本文档只收录程序源代码；设计文档（需求分析、工程意图、软件设计、验证报告、")
    add("> V2.0 需求演化与设计调整）位于工作文件夹的 `docs/` 目录下，另有独立文件。\n")

    add("## 工作文件夹\n")
    add("```")
    add(str(PROJECT).replace("\\", "/"))
    add("```\n")

    add("## 一、项目概况\n")
    add("| 项目 | 内容 |")
    add("|---|---|")
    add("| 实验项目 | 校园活动管理系统 V2.0（在 V1.0 基础上迭代） |")
    add("| 技术栈 | Python Flask + Flask-SQLAlchemy + Flask-Login + SQLite + Jinja2 |")
    add("| 前端方式 | 服务端渲染，原生 CSS，无构建链 |")
    add("| 数据库 | SQLite 单文件（`instance/campus.db`，已被 .gitignore 排除） |")
    add("| 版本管理 | Git　公开仓库 https://github.com/ShunyMifuky/SE_campus-activity-system |")
    add("| 源文件数 | SOURCE_FILE_COUNT 个 |")
    add("| 源代码规模 | 合计 SOURCE_LINE_COUNT 行 |")
    add(f"| Git 提交 | {git('rev-list', '--count', 'HEAD')} 次 |\n")

    add("## 二、Git 提交记录\n")
    add("```")
    add(git("log", "--pretty=format:%h  %ad  %s", "--date=format:%Y-%m-%d %H:%M"))
    add("```\n")

    add("## 三、目录结构\n")
    add("```")
    for path in iter_source_files():
        add("campus-activity-system/" + str(path.relative_to(PROJECT)).replace("\\", "/"))
    add("```\n")

    add("## 四、源代码\n")

    total_lines = 0
    shown = set()

    def emit(rel: str, path: Path):
        nonlocal total_lines
        content = path.read_text(encoding="utf-8", errors="ignore")
        line_count = len(content.splitlines())
        total_lines += line_count
        add(f"### `{rel}`　（{line_count} 行）\n")
        add(f"```{LANG.get(path.suffix, 'text')}")
        add(content.rstrip())
        add("```\n")

    for rel in ORDER:
        path = PROJECT / rel
        if not path.exists():
            continue
        shown.add(rel)
        emit(rel, path)

    # 兜底：订单里没列到的源码文件也一并收入，避免遗漏
    for path in iter_source_files():
        rel = str(path.relative_to(PROJECT)).replace("\\", "/")
        if rel in shown or path.suffix not in LANG:
            continue
        emit(rel, path)

    text = "\n".join(lines)
    text = text.replace("SOURCE_LINE_COUNT", str(total_lines))
    text = text.replace("SOURCE_FILE_COUNT", str(sum(1 for _ in iter_source_files())))
    DOC_PATH.write_text(text, encoding="utf-8")
    return total_lines


def main():
    count, total = build_zip()
    print(f"压缩包：{ZIP_PATH.name}　{count} 个文件，{total / 1024:.0f} KB")
    lines = build_source_doc()
    print(f"源代码汇编：{DOC_PATH.name}　共 {lines} 行")


if __name__ == "__main__":
    main()

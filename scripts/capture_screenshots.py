"""生成实验报告所需的关键界面截图。

这是开发辅助脚本，不属于 V1.0 运行时依赖。
使用前需要：
    1. 安装依赖：pip install playwright
    2. 本机已安装 Chrome（脚本通过 channel="chrome" 复用系统浏览器，不额外下载）
    3. 已执行：python -m app.seed --reset

用法：
    python scripts/capture_screenshots.py
截图输出到 docs/screenshots/。
"""

import os
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = BASE_DIR / "docs" / "screenshots"
BASE_URL = os.environ.get("TARGET_URL", "http://127.0.0.1:5000")
DEMO_PASSWORD = "Demo@2026"
VIEWPORT = {"width": 1280, "height": 860}


def prepare_demo_data() -> None:
    """重置演示数据，并制造一些报名记录，让截图内容有代表性。"""
    python = sys.executable
    subprocess.run([python, "-m", "app.seed", "--reset"], cwd=BASE_DIR, check=True)

    # 这里刻意只用标准库完成登录与报名，避免为截图脚本引入额外依赖
    helper = r"""
import http.cookiejar, urllib.parse, urllib.request

BASE = "http://127.0.0.1:5000"
PW = "Demo@2026"

# 活动 1：报名 3 人（用于展示报名名单）
# 活动 2：报名 1 人（用于展示"已报名"与"可报名"两种详情页形态）
PLAN = {
    "linxiangyu": [1, 2],
    "chenjiahe": [1],
    "zhaoyiming": [1],
}


def session_for(username):
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    payload = urllib.parse.urlencode({"username": username, "password": PW}).encode()
    opener.open(BASE + "/auth/login", payload)
    return opener


for username, activity_ids in PLAN.items():
    opener = session_for(username)
    for activity_id in activity_ids:
        opener.open(BASE + f"/activities/{activity_id}/signup", data=b"")

print("演示报名数据已写入")
"""
    subprocess.run([python, "-c", helper], cwd=BASE_DIR, check=True)


def login(page, username: str) -> None:
    page.goto(f"{BASE_URL}/auth/login")
    page.fill('input[name="username"]', username)
    page.fill('input[name="password"]', DEMO_PASSWORD)
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle")


def shoot(page, name: str, path: str, *, full_page: bool = True) -> None:
    page.goto(f"{BASE_URL}{path}")
    page.wait_for_load_state("networkidle")
    page.screenshot(path=str(OUT_DIR / f"{name}.png"), full_page=full_page)
    print(f"  已保存 {name}.png  <- {path}")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    prepare_demo_data()

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)

        # ---------- 未登录（访客视角） ----------
        guest = browser.new_context(viewport=VIEWPORT, device_scale_factor=2)
        page = guest.new_page()
        print("访客视角：")
        shoot(page, "01-活动列表-访客", "/")
        shoot(page, "02-活动列表-筛选结果", "/activities?status=open&category=1")
        shoot(page, "03-活动详情-访客", "/activities/1")
        shoot(page, "04-注册页", "/auth/register")
        guest.close()

        # ---------- 学生视角 ----------
        student = browser.new_context(viewport=VIEWPORT, device_scale_factor=2)
        page = student.new_page()
        login(page, "linxiangyu")
        print("学生视角：")
        shoot(page, "05-活动详情-学生可报名", "/activities/2")
        shoot(page, "06-活动详情-学生已报名", "/activities/1")
        shoot(page, "07-我的报名", "/my/registrations")
        student.close()

        # ---------- 教师视角 ----------
        teacher = browser.new_context(viewport=VIEWPORT, device_scale_factor=2)
        page = teacher.new_page()
        login(page, "wangtairan")
        print("教师视角：")
        shoot(page, "08-我的活动", "/my/activities")
        shoot(page, "09-发布活动表单", "/activities/new")
        shoot(page, "10-报名名单与操作记录", "/activities/1/signups")
        teacher.close()

        browser.close()

    print(f"\n全部截图已输出到：{OUT_DIR}")


if __name__ == "__main__":
    main()

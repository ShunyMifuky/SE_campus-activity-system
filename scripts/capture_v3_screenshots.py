"""实验三报告截图（V3.0 新增界面）。

前置：
    python -m app.seed --reset
    python run.py            # 另开终端，监听 127.0.0.1:5000

用法：
    python scripts/capture_v3_screenshots.py
输出到 docs/screenshots/，文件名以 11- 起，避免覆盖 V1/V2 的截图。
"""

import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = BASE_DIR / "docs" / "screenshots"
BASE_URL = os.environ.get("TARGET_URL", "http://127.0.0.1:5000")
PASSWORD = "Demo@2026"


def login(page, username):
    # 已登录时 /auth/login 会直接跳走，先登出再登录
    page.goto(f"{BASE_URL}/auth/logout")
    page.goto(f"{BASE_URL}/auth/login")
    page.fill('input[name="username"]', username)
    page.fill('input[name="password"]', PASSWORD)
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle")


def open_activity(page, title):
    page.goto(f"{BASE_URL}/activities")
    page.get_by_role("link", name=title).first.click()
    page.wait_for_load_state("networkidle")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome",
            headless=True,
            # 本机可能注入了系统代理，localhost 必须绕过，否则截图会拿到代理错误页
            args=["--no-proxy-server", "--proxy-bypass-list=*"],
        )
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.on("dialog", lambda dialog: dialog.accept())

        # 11 列表页：快捷筛选 chips + 卡片信息密度
        page.goto(f"{BASE_URL}/activities")
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(OUT_DIR / "11-活动列表-快捷筛选.png"), full_page=True)

        # 12 报名结果页：真实走一遍报名
        login(page, "chenjiahe")
        open_activity(page, "校园羽毛球混合双打赛")
        page.get_by_role("button", name="立即报名").click()
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(OUT_DIR / "12-报名结果页.png"), full_page=True)

        # 13 通知中心：制造一次候补递补
        login(page, "linxiangyu")
        open_activity(page, "摄影基础工作坊（名额有限）")
        page.get_by_role("button", name="取消报名").click()
        page.wait_for_load_state("networkidle")

        login(page, "zhaoyiming")
        page.goto(f"{BASE_URL}/notifications")
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(OUT_DIR / "13-通知中心.png"), full_page=True)

        # 14 我的报名：候补/已通过的状态与更新时间
        page.goto(f"{BASE_URL}/my/registrations")
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(OUT_DIR / "14-我的报名-状态透明.png"), full_page=True)

        # 15 移动端列表（数据中移动端占 71%）
        mobile = browser.new_page(viewport={"width": 390, "height": 844})
        mobile.goto(f"{BASE_URL}/activities")
        mobile.wait_for_load_state("networkidle")
        mobile.screenshot(path=str(OUT_DIR / "15-移动端-活动列表.png"), full_page=True)

        browser.close()
    print("截图已输出到", OUT_DIR)


if __name__ == "__main__":
    sys.exit(main())

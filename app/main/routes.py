"""首页与可用性探针。"""

from flask import Blueprint, render_template

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    return render_template("index.html")


@main_bp.route("/healthz")
def healthz():
    """最小可用性探针，供开发与验证阶段确认服务已启动。"""
    return {"status": "ok", "app": "校园活动管理系统", "version": "V1.0"}

"""运维与探针接口。

说明：首页由活动列表承担（REQ-04），因此本模块只保留可用性探针。
"""

from flask import Blueprint

main_bp = Blueprint("main", __name__)


@main_bp.route("/healthz")
def healthz():
    """最小可用性探针，供开发与验证阶段确认服务已启动。"""
    return {"status": "ok", "app": "校园活动管理系统", "version": "V1.0"}

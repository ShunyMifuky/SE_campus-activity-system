"""通知蓝图（V3.0 R-14）。"""

from flask import Blueprint

notifications_bp = Blueprint("notifications", __name__)

from . import routes  # noqa: E402,F401  （蓝图定义后导入视图，避免循环引用）

"""通知模块（V3.0 R-14）。

状态变化必须主动触达，不能依赖用户自己去刷新「我的报名」。
本蓝图的职责很窄：列出通知、标记已读、点开跳转。
通知的**产生**发生在业务服务里（审核、递补、下架），与状态变更同事务。
"""

from flask import abort, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..extensions import db
from ..models import Notification, now
from . import notifications_bp

# 单个用户一次最多展示的历史通知条数
LIST_LIMIT = 100


@notifications_bp.route("/notifications")
@login_required
def index():
    items = (
        Notification.query.filter_by(user_id=current_user.id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(LIST_LIMIT)
        .all()
    )
    unread = sum(1 for item in items if item.is_unread)
    return render_template("notifications/index.html", notifications=items, unread=unread)


@notifications_bp.route("/notifications/<int:notification_id>/open")
@login_required
def open_notification(notification_id: int):
    """点开一条通知：标记已读并跳到相关页面。"""
    item = db.session.get(Notification, notification_id)
    if item is None or item.user_id != current_user.id:
        abort(404)  # 不暴露他人通知是否存在

    if item.read_at is None:
        item.read_at = now()
        db.session.commit()

    if item.activity_id:
        return redirect(url_for("activities.detail", activity_id=item.activity_id))
    return redirect(url_for("registrations.mine"))


@notifications_bp.route("/notifications/<int:notification_id>/read", methods=["POST"])
@login_required
def mark_read(notification_id: int):
    item = db.session.get(Notification, notification_id)
    if item is None or item.user_id != current_user.id:
        abort(404)
    if item.read_at is None:
        item.read_at = now()
        db.session.commit()
    return redirect(_back_target())


@notifications_bp.route("/notifications/read-all", methods=["POST"])
@login_required
def mark_all_read():
    Notification.query.filter_by(user_id=current_user.id, read_at=None).update(
        {"read_at": now()}, synchronize_session=False
    )
    db.session.commit()
    return redirect(_back_target())


def _back_target():
    """回到来源页；只接受站内相对路径，避免开放重定向。"""
    target = (request.form.get("next") or "").strip()
    if target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("notifications.index")

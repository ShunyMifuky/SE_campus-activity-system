"""报名模块。

  REQ-05 学生报名与取消报名
  REQ-06 教师查看报名名单与名额统计

视图层只负责取参数、调用 service、把结果转成 flash 提示。
"""

from flask import Blueprint, abort, flash, redirect, render_template, url_for
from flask_login import current_user

from ..decorators import ensure_resource_owner, student_required, teacher_required
from ..extensions import db
from ..models import Activity, OperationLog
from ..services import registration_service

registrations_bp = Blueprint("registrations", __name__)

# 报名名单页面展示的操作记录条数
RECENT_LOG_LIMIT = 20


def _get_activity_or_404(activity_id: int) -> Activity:
    activity = db.session.get(Activity, activity_id)
    if activity is None:
        abort(404)
    return activity


@registrations_bp.route("/activities/<int:activity_id>/signup", methods=["POST"])
@student_required
def signup(activity_id: int):
    activity = _get_activity_or_404(activity_id)
    ok, message = registration_service.signup(activity, current_user)
    flash(message, "success" if ok else "danger")
    return redirect(url_for("activities.detail", activity_id=activity.id))


@registrations_bp.route("/activities/<int:activity_id>/cancel-signup", methods=["POST"])
@student_required
def cancel_signup(activity_id: int):
    activity = _get_activity_or_404(activity_id)
    ok, message = registration_service.cancel_signup(activity, current_user)
    flash(message, "info" if ok else "warning")
    return redirect(url_for("activities.detail", activity_id=activity.id))


@registrations_bp.route("/my/registrations")
@student_required
def mine():
    registrations = registration_service.find_my_registrations(current_user)
    return render_template("registrations/mine.html", registrations=registrations)


@registrations_bp.route("/activities/<int:activity_id>/signups")
@teacher_required
def roster(activity_id: int):
    """教师查看某活动的报名名单与名额统计（REQ-06）。"""
    activity = _get_activity_or_404(activity_id)
    ensure_resource_owner(activity)  # 约束 C3：报名名单只对活动发布者开放

    # 名单按报名先后排序，便于教师按顺序通知或分组
    registrations = sorted(activity.registrations, key=lambda r: (r.created_at, r.id))

    # 该活动的关键操作记录，用于说明"谁在什么时候做了什么"
    logs = (
        OperationLog.query.filter_by(target_type="activity", target_id=activity.id)
        .order_by(OperationLog.created_at.desc(), OperationLog.id.desc())
        .limit(RECENT_LOG_LIMIT)
        .all()
    )

    return render_template(
        "registrations/roster.html",
        activity=activity,
        registrations=registrations,
        logs=logs,
    )

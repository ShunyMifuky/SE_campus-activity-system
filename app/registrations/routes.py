"""报名模块（V2.0）。

  R-01 候补申请      R-02 空位自动递补      R-03 退出候补
  R-05 报名审核      R-07 报名状态可见      R-09 名单与状态

视图层只负责取参数、调用 service、把结果转成 flash 提示。
"""

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ..decorators import ensure_resource_owner, student_required, teacher_required
from ..extensions import db
from ..models import REG_APPROVED, Activity, OperationLog, Registration
from ..services import registration_service

registrations_bp = Blueprint("registrations", __name__)

# 报名名单页面展示的操作记录条数
RECENT_LOG_LIMIT = 20


def _get_activity_or_404(activity_id: int) -> Activity:
    activity = db.session.get(Activity, activity_id)
    if activity is None:
        abort(404)
    return activity


# ------------------------------------------------------------------ 学生操作
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


@registrations_bp.route("/activities/<int:activity_id>/exit-waitlist", methods=["POST"])
@student_required
def exit_waitlist(activity_id: int):
    """退出候补（R-03）。

    与取消报名分开成两个入口——教师场第 22 组明确二者不是一回事：
    退出候补不释放正式名额，因此也不会触发递补。
    """
    activity = _get_activity_or_404(activity_id)
    ok, message = registration_service.exit_waitlist(activity, current_user)
    flash(message, "info" if ok else "warning")
    return redirect(url_for("activities.detail", activity_id=activity.id))


@registrations_bp.route("/my/registrations")
@student_required
def mine():
    registrations = registration_service.find_my_registrations(current_user)
    return render_template("registrations/mine.html", registrations=registrations)


# ------------------------------------------------------------------ 教师操作
@registrations_bp.route("/activities/<int:activity_id>/signups")
@teacher_required
def roster(activity_id: int):
    """教师查看某活动的报名名单、待审核申请与名额统计（R-09）。"""
    activity = _get_activity_or_404(activity_id)
    ensure_resource_owner(activity)  # 约束 C3：名单只对活动发布者开放

    roster_groups = registration_service.group_roster(activity)
    pending = registration_service.find_pending_registrations(activity)

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
        roster=roster_groups,
        pending=pending,
        registrations=roster_groups[REG_APPROVED],  # 兼容原有模板变量
        logs=logs,
    )


@registrations_bp.route(
    "/activities/<int:activity_id>/registrations/<int:registration_id>/review",
    methods=["POST"],
)
@teacher_required
def review(activity_id: int, registration_id: int):
    """教师审核报名申请（R-05 通过／拒绝，R-06 先资格后名额）。"""
    activity = _get_activity_or_404(activity_id)
    ensure_resource_owner(activity)  # 约束 C3：只能审核本人负责的活动

    registration = db.session.get(Registration, registration_id)
    if registration is None or registration.activity_id != activity.id:
        abort(404)

    decision = (request.form.get("decision") or "").strip()
    if decision not in ("approve", "reject"):
        flash("审核操作无效。", "warning")
        return redirect(url_for("registrations.roster", activity_id=activity.id))

    ok, message = registration_service.review_registration(
        activity, registration, current_user, approve=(decision == "approve")
    )
    flash(message, "success" if ok else "warning")
    return redirect(url_for("registrations.roster", activity_id=activity.id))

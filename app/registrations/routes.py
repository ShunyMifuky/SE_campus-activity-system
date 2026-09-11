"""报名模块。

  REQ-05 学生报名与取消报名
  REQ-06 教师查看报名名单（下一步接入）

视图层只负责取参数、调用 service、把结果转成 flash 提示。
"""

from flask import Blueprint, abort, flash, redirect, render_template, url_for
from flask_login import current_user

from ..decorators import student_required
from ..extensions import db
from ..models import Activity
from ..services import registration_service

registrations_bp = Blueprint("registrations", __name__)


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

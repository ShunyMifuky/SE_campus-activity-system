"""管理员路由：账号管理与平台活动监管（R-09）。

边界（访谈确认，管理员第 3／5／6 组）：
  - 管：用户账号与状态、角色与权限、全部活动信息的监管
  - 不管：具体人数、参加资格、候补顺序、报名审核——这些一律归活动组织教师
"""

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ..decorators import admin_required
from ..extensions import db
from ..models import (
    FILTERABLE_STATUSES,
    ROLE_LABELS,
    Activity,
    User,
    log_operation,
)
from ..services import activity_service

admin_bp = Blueprint("admin", __name__)


# ------------------------------------------------------------ 账号管理
@admin_bp.route("/users")
@admin_required
def users():
    """平台用户账号列表（R-09：可查看账号与基本状态）。"""
    role = (request.args.get("role") or "").strip()
    state = (request.args.get("state") or "").strip()

    query = User.query
    if role in ROLE_LABELS:
        query = query.filter_by(role=role)
    if state == "enabled":
        query = query.filter_by(enabled=True)
    elif state == "disabled":
        query = query.filter_by(enabled=False)

    user_list = query.order_by(User.role, User.id).all()

    return render_template(
        "admin/users.html",
        users=user_list,
        role_filter=role,
        state_filter=state,
        role_labels=ROLE_LABELS,
        total=User.query.count(),
        disabled_total=User.query.filter_by(enabled=False).count(),
    )


@admin_bp.route("/users/<int:user_id>/toggle", methods=["POST"])
@admin_required
def toggle_user(user_id: int):
    """停用 / 恢复账号（R-09）。

    停用只影响登录，**不改变该用户已有的报名记录**——
    这一项在访谈中没有得到明确规则（管理员第 7 组追问），本轮按最简处理。
    """
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)

    if user.id == current_user.id:
        flash("不能停用当前登录的管理员账号。", "warning")
        return redirect(url_for("admin.users"))

    user.enabled = not user.enabled
    log_operation(
        current_user,
        action="enable_user" if user.enabled else "disable_user",
        target_type="user",
        target_id=user.id,
        detail=f"{'恢复' if user.enabled else '停用'}账号 {user.username}（{user.real_name}）",
    )
    db.session.commit()
    flash(f"已{'恢复' if user.enabled else '停用'}账号：{user.real_name}。", "info")
    return redirect(url_for("admin.users"))


# ------------------------------------------------------------ 活动监管
@admin_bp.route("/activities")
@admin_required
def activities():
    """平台全部活动（R-09：可查看全部活动，含非本人发布）。"""
    status = (request.args.get("status") or "").strip()
    keyword = (request.args.get("q") or "").strip()

    items = Activity.query.order_by(Activity.created_at.desc()).all()
    if status in FILTERABLE_STATUSES:
        items = [a for a in items if a.status == status]
    if keyword:
        items = [
            a
            for a in items
            if keyword in a.title
            or keyword in a.location
            or keyword in a.creator.real_name
        ]

    all_activities = Activity.query.all()

    return render_template(
        "admin/activities.html",
        activities=items,
        status_filter=status,
        keyword=keyword,
        total=len(all_activities),
        canceled_total=sum(1 for a in all_activities if a.canceled_at is not None),
    )


@admin_bp.route("/activities/<int:activity_id>/cancel", methods=["POST"])
@admin_required
def cancel_activity(activity_id: int):
    """从平台层面下架违规或明显错误的活动（R-09）。

    复用 V1.0 的软下架（设计决策 D5／D12）——保留历史与报名数据。
    管理员**不能**修改人数上限、参加资格、候补顺序与审核结果。
    """
    activity = db.session.get(Activity, activity_id)
    if activity is None:
        abort(404)

    errors = activity_service.cancel_activity(activity, current_user)
    if errors:
        flash(errors[0], "warning")
    else:
        flash(f"已下架活动：《{activity.title}》。", "info")
    return redirect(url_for("admin.activities"))

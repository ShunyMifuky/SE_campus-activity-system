"""活动模块。

  REQ-03 活动发布、修改与下架（教师侧）
  REQ-04 活动列表、筛选与详情（公共侧，未登录可访问）

视图层只负责：取参数 → 调用 service → 渲染结果。
"""

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ..decorators import teacher_required
from ..extensions import db
from ..models import (
    FILTERABLE_STATUSES,
    STATUS_CANCELED,
    Activity,
    Category,
)
from ..services import activity_service

activities_bp = Blueprint("activities", __name__)


# ------------------------------------------------------------ REQ-04 浏览
@activities_bp.route("/")
@activities_bp.route("/activities")
def list_activities():
    keyword = (request.args.get("q") or "").strip()
    category_raw = (request.args.get("category") or "").strip()
    status = (request.args.get("status") or "").strip()

    query = Activity.query
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            db.or_(
                Activity.title.like(like),
                Activity.summary.like(like),
                Activity.location.like(like),
            )
        )

    if category_raw.isdigit():
        query = query.filter(Activity.category_id == int(category_raw))

    items = query.order_by(Activity.start_time.asc()).all()

    # 设计决策 D3：活动状态是推导值，无法用 SQL 直接过滤，因此在这里筛选
    if status in FILTERABLE_STATUSES:
        items = [a for a in items if a.status == status]
    else:
        # 设计决策 D5：未指定状态时，公共列表默认不展示已下架活动
        items = [a for a in items if a.status != STATUS_CANCELED]

    categories = Category.query.order_by(Category.sort_order).all()
    return render_template(
        "activities/list.html",
        activities=items,
        categories=categories,
        filters={"q": keyword, "category": category_raw, "status": status},
    )


@activities_bp.route("/activities/<int:activity_id>")
def detail(activity_id: int):
    activity = db.session.get(Activity, activity_id)
    if activity is None:
        abort(404)
    return render_template("activities/detail.html", activity=activity)


# ------------------------------------------------------------ REQ-03 管理
@activities_bp.route("/my/activities")
@teacher_required
def mine():
    items = (
        Activity.query.filter_by(creator_id=current_user.id)
        .order_by(Activity.start_time.desc())
        .all()
    )
    return render_template("activities/mine.html", activities=items)


@activities_bp.route("/activities/new", methods=["GET", "POST"])
@teacher_required
def create():
    categories = Category.query.order_by(Category.sort_order).all()

    if request.method == "POST":
        activity, errors = activity_service.create_activity(current_user, request.form)
        if errors:
            for message in errors:
                flash(message, "danger")
            return render_template(
                "activities/form.html",
                activity=None,
                categories=categories,
                values=activity_service.form_values(form=request.form),
            )
        flash(f"活动《{activity.title}》已发布。", "success")
        return redirect(url_for("activities.detail", activity_id=activity.id))

    return render_template(
        "activities/form.html",
        activity=None,
        categories=categories,
        values=activity_service.form_values(),
    )


@activities_bp.route("/activities/<int:activity_id>/edit", methods=["GET", "POST"])
@teacher_required
def edit(activity_id: int):
    activity = db.session.get(Activity, activity_id)
    if activity is None:
        abort(404)

    if request.method == "POST":
        errors = activity_service.update_activity(activity, current_user, request.form)
        if errors:
            for message in errors:
                flash(message, "danger")
            return render_template(
                "activities/form.html",
                activity=activity,
                categories=Category.query.order_by(Category.sort_order).all(),
                values=activity_service.form_values(activity, request.form),
            )
        flash(f"活动《{activity.title}》已更新。", "success")
        return redirect(url_for("activities.detail", activity_id=activity.id))

    return render_template(
        "activities/form.html",
        activity=activity,
        categories=Category.query.order_by(Category.sort_order).all(),
        values=activity_service.form_values(activity),
    )


@activities_bp.route("/activities/<int:activity_id>/cancel", methods=["POST"])
@teacher_required
def cancel(activity_id: int):
    activity = db.session.get(Activity, activity_id)
    if activity is None:
        abort(404)

    errors = activity_service.cancel_activity(activity, current_user)
    if errors:
        for message in errors:
            flash(message, "warning")
    else:
        flash(f"活动《{activity.title}》已下架。", "info")

    return redirect(url_for("activities.detail", activity_id=activity.id))

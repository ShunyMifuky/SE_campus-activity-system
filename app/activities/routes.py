"""活动模块。

  REQ-03 活动发布、修改与下架（教师侧）
  REQ-04 活动列表、筛选与详情（公共侧，未登录可访问）

视图层只负责：取参数 → 调用 service → 渲染结果。
"""

from datetime import datetime, time, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ..decorators import ensure_resource_owner, teacher_required
from ..extensions import db
from ..models import (
    FILTERABLE_STATUSES,
    STATUS_CANCELED,
    Activity,
    Category,
    now,
)
from ..services import activity_service

activities_bp = Blueprint("activities", __name__)


# ------------------------------------------------------------ REQ-04 浏览
def _weekend_range(reference: datetime):
    """「本周末」的时间区间：周六 00:00 ~ 周一 00:00。

    若今天是周日，则落在「今天」所在的这个周末，而不是下一个周末——
    否则周日的用户点「本周末」会看到六天后的活动，与直觉不符。
    """
    today = reference.date()
    weekday = today.weekday()          # 周一=0，周日=6
    if weekday == 6:
        saturday = today - timedelta(days=1)
    else:
        saturday = today + timedelta(days=5 - weekday)
    start = datetime.combine(saturday, time.min)
    return start, start + timedelta(days=2)


@activities_bp.route("/")
@activities_bp.route("/activities")
def list_activities():
    keyword = (request.args.get("q") or "").strip()
    category_raw = (request.args.get("category") or "").strip()
    status = (request.args.get("status") or "").strip()
    # V3.0 R-16：三个快捷筛选维度
    when = (request.args.get("when") or "").strip()
    only_vacancy = (request.args.get("vacancy") or "") == "1"
    no_review = (request.args.get("review") or "") == "0"

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

    # 时间与审核要求都是数据库字段，直接下推到 SQL（设计决策 D-17）
    if when == "weekend":
        start, end = _weekend_range(now())
        query = query.filter(Activity.start_time >= start, Activity.start_time < end)
    elif when == "week":
        start = now()
        query = query.filter(
            Activity.start_time >= start,
            Activity.start_time < start + timedelta(days=7),
        )

    if no_review:
        query = query.filter(Activity.requires_review.is_(False))

    items = query.order_by(Activity.start_time.asc()).all()

    # 设计决策 D3：活动状态是推导值，无法用 SQL 直接过滤，因此在这里筛选
    if status in FILTERABLE_STATUSES:
        items = [a for a in items if a.status == status]
    else:
        # 设计决策 D5：未指定状态时，公共列表默认不展示已下架活动
        items = [a for a in items if a.status != STATUS_CANCELED]

    # 有名额同样依赖 approved_count（推导值），只能在内存层过滤。
    # 「还有名额」隐含「现在还能报名」，因此顺带排除已截止/进行中的活动。
    if only_vacancy:
        items = [a for a in items if a.is_signup_open and a.has_vacancy]

    categories = Category.query.order_by(Category.sort_order).all()
    filters = {
        "q": keyword,
        "category": category_raw,
        "status": status,
        "when": when,
        "vacancy": "1" if only_vacancy else "",
        "review": "0" if no_review else "",
    }

    def filter_url(**overrides):
        """保留当前筛选条件，只改其中一项（供快捷筛选 chip 使用）。"""
        merged = {**filters, **overrides}
        params = {k: v for k, v in merged.items() if v not in (None, "")}
        return url_for("activities.list_activities", **params)

    return render_template(
        "activities/list.html",
        activities=items,
        categories=categories,
        filters=filters,
        filter_url=filter_url,
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
    ensure_resource_owner(activity)  # 约束 C3：只能修改自己发布的活动

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
    ensure_resource_owner(activity)  # 约束 C3：只能下架自己发布的活动

    errors = activity_service.cancel_activity(activity, current_user)
    if errors:
        for message in errors:
            flash(message, "warning")
    else:
        flash(f"活动《{activity.title}》已下架。", "info")

    return redirect(url_for("activities.detail", activity_id=activity.id))

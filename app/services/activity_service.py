"""活动相关业务规则（对应 REQ-03）。

设计决策 D2：表单校验与状态变更规则集中在这里，视图层不写业务判断。

可被识别的错误统一以"错误信息列表"形式返回，由视图层负责转成 flash 提示——
这样 service 层不依赖任何 Web 框架的上下文，便于单独测试。
"""

from datetime import datetime

from ..extensions import db
from ..models import Activity, Category, log_operation, now

# 允许的日期时间输入格式：datetime-local 控件提交的是第一种
DATETIME_FORMATS = ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M")

MAX_TITLE_LENGTH = 120
MAX_SUMMARY_LENGTH = 500
MAX_LOCATION_LENGTH = 120
MAX_CAPACITY = 100000


def parse_datetime(raw_value, label: str, errors: list):
    """解析日期时间输入；失败时写入错误信息并返回 None。"""
    text = (raw_value or "").strip()
    if not text:
        errors.append(f"{label}不能为空。")
        return None
    for fmt in DATETIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    errors.append(f"{label}格式不正确，请使用 YYYY-MM-DD HH:MM 格式。")
    return None


def parse_capacity(raw_value, errors: list):
    """解析人数上限；0 表示不限人数（见设计文档 4.3）。"""
    text = (raw_value or "").strip()
    if text == "":
        return 0
    try:
        value = int(text)
    except ValueError:
        errors.append("人数上限必须是整数。")
        return 0
    if value < 0:
        errors.append("人数上限不能为负数。")
        return 0
    if value > MAX_CAPACITY:
        errors.append(f"人数上限不能超过 {MAX_CAPACITY}。")
        return 0
    return value


def collect_activity_form(form):
    """从表单收集并校验活动字段，返回 (payload, errors)。"""
    errors = []

    title = (form.get("title") or "").strip()
    summary = (form.get("summary") or "").strip()
    location = (form.get("location") or "").strip()
    category_raw = (form.get("category_id") or "").strip()

    start_time = parse_datetime(form.get("start_time"), "活动开始时间", errors)
    end_time = parse_datetime(form.get("end_time"), "活动结束时间", errors)
    deadline = parse_datetime(form.get("signup_deadline"), "报名截止时间", errors)
    capacity = parse_capacity(form.get("capacity"), errors)

    if not title:
        errors.append("活动名称不能为空。")
    elif len(title) > MAX_TITLE_LENGTH:
        errors.append(f"活动名称不能超过 {MAX_TITLE_LENGTH} 个字符。")

    if len(summary) > MAX_SUMMARY_LENGTH:
        errors.append(f"活动简介不能超过 {MAX_SUMMARY_LENGTH} 个字符。")

    if not location:
        errors.append("活动地点不能为空。")
    elif len(location) > MAX_LOCATION_LENGTH:
        errors.append(f"活动地点不能超过 {MAX_LOCATION_LENGTH} 个字符。")

    category_id = None
    if category_raw:
        if category_raw.isdigit() and db.session.get(Category, int(category_raw)) is not None:
            category_id = int(category_raw)
        else:
            errors.append("请选择有效的活动分类。")

    # 时间先后关系：展示给用户前先保证语义正确
    if start_time and end_time and end_time <= start_time:
        errors.append("活动结束时间必须晚于开始时间。")
    if start_time and deadline and deadline > start_time:
        errors.append("报名截止时间不能晚于活动开始时间。")

    payload = {
        "title": title,
        "summary": summary,
        "location": location,
        "category_id": category_id,
        "start_time": start_time,
        "end_time": end_time,
        "signup_deadline": deadline,
        "capacity": capacity,
    }
    return payload, errors


def create_activity(creator, form):
    """教师发布活动。返回 (activity, errors)。"""
    payload, errors = collect_activity_form(form)
    if errors:
        return None, errors

    activity = Activity(creator_id=creator.id, **payload)
    db.session.add(activity)
    db.session.flush()  # 先拿到自增 id，供日志引用

    log_operation(
        creator,
        action="create_activity",
        target_type="activity",
        target_id=activity.id,
        detail=f"发布活动《{activity.title}》",
    )
    db.session.commit()
    return activity, []


def update_activity(activity, actor, form):
    """修改活动。返回错误信息列表。"""
    payload, errors = collect_activity_form(form)
    if errors:
        return errors

    # 人数上限不能被改到小于当前已报名人数，否则会出现"已超额"的矛盾状态
    new_capacity = payload["capacity"]
    if new_capacity and new_capacity < activity.registered_count:
        return [f"人数上限不能小于当前已报名人数（{activity.registered_count} 人）。"]

    for field, value in payload.items():
        setattr(activity, field, value)

    log_operation(
        actor,
        action="update_activity",
        target_type="activity",
        target_id=activity.id,
        detail=f"修改活动《{activity.title}》",
    )
    db.session.commit()
    return []


def cancel_activity(activity, actor):
    """下架活动（设计决策 D5：软下架，保留历史报名数据）。返回错误信息列表。"""
    if activity.canceled_at is not None:
        return ["该活动已经下架，无需重复操作。"]

    activity.canceled_at = now()
    log_operation(
        actor,
        action="cancel_activity",
        target_type="activity",
        target_id=activity.id,
        detail=f"下架活动《{activity.title}》",
    )
    db.session.commit()
    return []


def form_values(activity=None, form=None) -> dict:
    """为模板准备表单回填值：优先取用户刚提交的内容，其次取活动现有值。

    说明：编辑页在提交失败后需要保留用户输入，因此 form 优先。
    """
    form = form if form is not None else {}

    def pick(key, default=""):
        submitted = form.get(key)
        if submitted not in (None, ""):
            return submitted
        if activity is not None:
            value = getattr(activity, key, None)
            if isinstance(value, datetime):
                return value.strftime("%Y-%m-%dT%H:%M")
            if value is not None:
                return str(value)
        return default

    return {
        "title": pick("title"),
        "summary": pick("summary"),
        "location": pick("location"),
        "category_id": pick("category_id"),
        "start_time": pick("start_time"),
        "end_time": pick("end_time"),
        "signup_deadline": pick("signup_deadline"),
        "capacity": pick("capacity", "0"),
    }

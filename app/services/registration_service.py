"""报名相关业务规则（对应 REQ-05）。

设计决策 D2：报名校验集中在这里，视图层不做业务判断——
否则"详情页隐藏按钮"就成了唯一的防线，绕过页面直接提交请求即可突破规则。
"""

from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import ROLE_STUDENT, STATUS_CANCELED, Registration, log_operation, now


def signup(activity, user):
    """学生报名活动。返回 (是否成功, 提示信息)。"""
    # 角色校验：教师账号不参与报名
    if user.role != ROLE_STUDENT:
        return False, "只有学生账号可以报名活动。"

    # 活动必须处于可报名状态（已下架的活动不可报名）
    if activity.status == STATUS_CANCELED:
        return False, "该活动已下架，无法报名。"

    # 报名截止校验（约束 C2）
    # 页面在截止后会隐藏报名按钮，但按钮隐藏只是体验，不能当作规则：
    # 直接向报名接口提交请求同样必须被拒绝。
    if now() > activity.signup_deadline:
        deadline_text = activity.signup_deadline.strftime("%Y-%m-%d %H:%M")
        return False, f"该活动报名已截止（截止时间 {deadline_text}），无法报名。"

    # 重复报名校验
    # 注意：这一项必须排在名额校验之前。若本人已报名且恰好占满了最后一个名额，
    # 先判名额会提示"名额已满"，让人误以为名额被别人抢走，实际是自己已经报过。
    if activity.has_registration_of(user):
        return False, "你已经报名过该活动，请勿重复报名。"

    # 名额校验
    if activity.is_full:
        return False, f"该活动名额已满（上限 {activity.capacity} 人），报名失败。"

    registration = Registration(activity_id=activity.id, user_id=user.id)
    db.session.add(registration)
    try:
        db.session.flush()  # 触发数据库唯一约束（设计决策 D4：最终防线）
    except IntegrityError:
        db.session.rollback()
        return False, "你已经报名过该活动，请勿重复报名。"

    log_operation(
        user,
        action="signup_activity",
        target_type="activity",
        target_id=activity.id,
        detail=f"报名活动《{activity.title}》",
    )
    db.session.commit()
    return True, f"报名成功：《{activity.title}》。请按时参加。"


def cancel_signup(activity, user):
    """学生取消报名。返回 (是否成功, 提示信息)。"""
    registration = Registration.query.filter_by(
        activity_id=activity.id, user_id=user.id
    ).first()

    if registration is None:
        return False, "你没有报名该活动，无需取消。"

    db.session.delete(registration)
    log_operation(
        user,
        action="cancel_signup",
        target_type="activity",
        target_id=activity.id,
        detail=f"取消报名活动《{activity.title}》",
    )
    db.session.commit()
    return True, f"已取消报名：《{activity.title}》。"


def find_my_registrations(user):
    """学生的报名记录，按报名时间倒序。"""
    return (
        Registration.query.filter_by(user_id=user.id)
        .order_by(Registration.created_at.desc())
        .all()
    )

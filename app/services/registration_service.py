"""报名相关业务规则（对应 R-01 ~ R-08）。

设计决策 D2（沿用 V1.0）：报名校验集中在这里，视图层不做业务判断——
否则"详情页隐藏按钮"就成了唯一的防线，绕过页面直接提交请求即可突破规则。

V2.0 的三处变化：
  1. 报名由一步动作改为**分支流程**：需要审核 → 待审核；否则按名额 → 已通过／候补中
  2. 取消不再删除记录，改为置为「已取消」，并在**同一事务内**触发候补递补
  3. 新增「退出候补」——它与取消报名语义不同（教师第 22 组）
"""

from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import (
    REG_APPROVED,
    REG_CANCELED,
    REG_PENDING,
    REG_REJECTED,
    REG_WAITLIST,
    ROLE_STUDENT,
    STATUS_CANCELED,
    Registration,
    log_operation,
    now,
)


# ============================================================ 报名
def signup(activity, user):
    """学生报名活动。返回 (是否成功, 提示信息)。"""
    # 角色校验：教师与管理员的账号都不参与报名
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

    # 重复报名校验（只拦「有效」记录：已取消／未通过的可以重新报名）
    existing = activity.registration_of(user)
    if existing is not None and existing.is_active:
        return False, _duplicate_message(existing)

    # 判定初始状态（R-04：先看活动是否需要审核；R-06：再看当时名额）
    if activity.requires_review:
        status = REG_PENDING
    elif activity.has_vacancy:
        status = REG_APPROVED
    else:
        status = REG_WAITLIST

    # 只有真正进入候补才记录入队时刻（D10 修订：候补排序按「进入候补的时间」）
    waitlisted_at = now() if status == REG_WAITLIST else None

    if existing is not None:
        # 复用原记录（设计决策 D9）：唯一约束下同一活动只有一条记录，
        # 直接改状态比"删除再新建"更干净，也保留了原始报名时间。
        existing.status = status
        existing.decided_at = now()
        existing.waitlisted_at = waitlisted_at
        registration = existing
    else:
        registration = Registration(
            activity_id=activity.id,
            user_id=user.id,
            status=status,
            waitlisted_at=waitlisted_at,
        )
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
        detail=f"报名活动《{activity.title}》（{registration.status_label}）",
    )
    db.session.commit()
    return True, _signup_message(activity, registration)


def _duplicate_message(registration):
    if registration.status == REG_PENDING:
        return "你已经提交过该活动的报名，正在等待组织教师审核。"
    if registration.status == REG_WAITLIST:
        return "你已在该活动的候补队列中，请勿重复报名。"
    return "你已经报名过该活动，请勿重复报名。"


def _signup_message(activity, registration):
    if registration.status == REG_PENDING:
        return f"已提交报名：《{activity.title}》。该活动需要审核，请等待组织教师确认。"
    if registration.status == REG_WAITLIST:
        pos = waitlist_position(activity, registration)
        return (
            f"该活动名额已满，你已进入候补队列（当前第 {pos} 位）：《{activity.title}》。"
            "有人取消时会按候补顺序自动补位。"
        )
    return f"报名成功：《{activity.title}》。请按时参加。"


# ============================================================ 候补
def waitlist_position(activity, registration) -> int:
    """该记录在当前候补队列中的位次（从 1 开始）。"""
    for index, item in enumerate(activity.waitlist_ordered, start=1):
        if item.id == registration.id:
            return index
    return len(activity.waitlist_ordered)


def _promote_from_waitlist(activity):
    """把空出的正式名额给候补顺序最靠前者（R-02，设计决策 D11）。

    在调用方的同一事务内同步完成，不引入定时任务或后台服务。
    三种情况不递补：人数不限、当前已无名额空缺、候补队列为空。
    """
    if not activity.capacity or not activity.has_vacancy:
        return None
    queue = activity.waitlist_ordered
    if not queue:
        return None
    promoted = queue[0]                 # 按进入候补的时间升序，最靠前者
    promoted.status = REG_APPROVED
    promoted.decided_at = now()
    promoted.waitlisted_at = None       # 已离开候补队列
    return promoted


# ============================================================ 取消 / 退出候补
def cancel_signup(activity, user):
    """学生取消报名（放弃正式名额或撤回待审核的申请）。返回 (ok, msg)。"""
    return _give_up(
        activity, user,
        allowed=(REG_APPROVED, REG_PENDING),
        action="cancel_signup",
        verb="取消报名",
    )


def exit_waitlist(activity, user):
    """学生退出候补。返回 (ok, msg)。

    与取消报名语义不同（教师第 22 组）：退出候补只是把自己从队列里去掉，
    不释放正式名额，因此**不触发递补**。
    """
    return _give_up(
        activity, user,
        allowed=(REG_WAITLIST,),
        action="exit_waitlist",
        verb="退出候补",
    )


def _give_up(activity, user, allowed, action, verb):
    registration = activity.registration_of(user)
    if registration is None or registration.status == REG_CANCELED:
        return False, f"你没有报名该活动，无需{verb}。"
    if registration.status not in allowed:
        return False, f"当前状态为「{registration.status_label}」，无法{verb}。"

    released = registration.occupies_slot      # 只有放弃正式名额才需要递补
    registration.status = REG_CANCELED
    registration.decided_at = now()
    registration.waitlisted_at = None          # 已离开候补队列

    promoted = _promote_from_waitlist(activity) if released else None

    log_operation(
        user,
        action=action,
        target_type="activity",
        target_id=activity.id,
        detail=f"{verb}活动《{activity.title}》",
    )
    if promoted is not None:
        log_operation(
            user,
            action="promote_waitlist",
            target_type="activity",
            target_id=activity.id,
            detail=f"候补递补：{promoted.user.real_name} 补入《{activity.title}》",
        )
    db.session.commit()

    message = f"已{verb}：《{activity.title}》。"
    if promoted is not None:
        message += f"空出的名额已自动补给了候补第一位的 {promoted.user.real_name}。"
    return True, message


# ============================================================ 审核
def review_registration(activity, registration, reviewer, approve: bool):
    """教师审核报名申请（R-05 通过／拒绝，R-06 先资格后名额）。返回 (ok, msg)。

    调用方（路由层）必须已确认：reviewer 是该活动的发布教师。
    """
    if registration.activity_id != activity.id:
        return False, "报名记录与活动不匹配。"
    if registration.status != REG_PENDING:
        return False, f"该申请当前状态为「{registration.status_label}」，无法审核。"

    name = registration.user.real_name

    if not approve:
        registration.status = REG_REJECTED
        registration.decided_at = now()
        log_operation(
            reviewer, action="review_reject", target_type="activity",
            target_id=activity.id,
            detail=f"拒绝 {name} 报名《{activity.title}》",
        )
        db.session.commit()
        return True, f"已拒绝 {name} 的报名申请。"

    # 通过 → 再看当时名额（R-06 的顺序：先资格、后名额）
    if activity.has_vacancy:
        registration.status = REG_APPROVED
        registration.waitlisted_at = None
        tail = "已确认为正式参加。"
    else:
        registration.status = REG_WAITLIST
        # 此刻才真正进入候补队列——候补排序以该时刻为准（访谈规则，D10 修订）
        registration.waitlisted_at = now()
        tail = "当时名额已满，已转入候补队列（按进入候补的时间排队）。"
    registration.decided_at = now()

    log_operation(
        reviewer, action="review_approve", target_type="activity",
        target_id=activity.id,
        detail=f"通过 {name} 报名《{activity.title}》（{registration.status_label}）",
    )
    db.session.commit()
    return True, f"已通过 {name} 的报名申请，{tail}"


# ============================================================ 查询
def find_my_registrations(user):
    """学生的报名记录，按报名时间倒序。"""
    return (
        Registration.query.filter_by(user_id=user.id)
        .order_by(Registration.created_at.desc())
        .all()
    )


def find_pending_registrations(activity):
    """某活动的待审核申请，按提交时间升序（先提交的先处理）。"""
    return sorted(
        (r for r in activity.registrations if r.status == REG_PENDING),
        key=lambda r: (r.created_at, r.id),
    )


def group_roster(activity):
    """活动的报名名单，按状态分组（供教师端分块展示）。"""
    buckets = {
        REG_APPROVED: [],
        REG_WAITLIST: [],
        REG_PENDING: [],
        REG_REJECTED: [],
        REG_CANCELED: [],
    }
    for r in sorted(activity.registrations, key=lambda r: (r.created_at, r.id)):
        buckets.setdefault(r.status, []).append(r)
    return buckets

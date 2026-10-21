"""报名相关业务规则（R-01 ~ R-16）。

设计决策 D2（沿用 V1.0）：报名校验集中在这里，视图层不做业务判断——
否则"详情页隐藏按钮"就成了唯一的防线，绕过页面直接提交请求即可突破规则。

V2.0 的三处变化：
  1. 报名由一步动作改为**分支流程**：需要审核 → 待审核；否则按名额 → 已通过／候补中
  2. 取消不再删除记录，改为置为「已取消」，并在**同一事务内**触发候补递补
  3. 新增「退出候补」——它与取消报名语义不同（教师第 22 组）

V3.0 的变化（数据驱动，见 docs/07-V3.0需求演化.md）：
  - R-10 报名提交幂等：同一 token 重复提交返回首次结果，不再报「请勿重复报名」
  - R-11 失败结果结构化：ok / code / reason / next_step / retryable
  - R-12 满员竞态不再以冲突错误结束，而是明确转入候补并给出位次
  - R-14 审核结果与候补递补写入站内通知，与状态变更同事务
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import (
    NOTIFY_ACTIVITY_CANCELED,
    NOTIFY_REVIEW_APPROVED,
    NOTIFY_REVIEW_REJECTED,
    NOTIFY_WAITLIST_PROMOTED,
    REG_ACTIVE,
    REG_APPROVED,
    REG_CANCELED,
    REG_PENDING,
    REG_REJECTED,
    REG_WAITLIST,
    ROLE_STUDENT,
    STATUS_CANCELED,
    Registration,
    SignupAttempt,
    log_operation,
    notify,
    now,
)

# 令牌只接受这一种形态；异常输入一律重新生成，避免把任意字符串当幂等键写库
TOKEN_PATTERN = re.compile(r"^[0-9a-f]{32}$")


# ============================================================ 结果对象
@dataclass(frozen=True)
class SignupResult:
    """一次报名提交的结果（R-11）。

    ok 的语义是「用户的意图是否已经实现」，不是「这次请求是否被服务端接受」：
    重复提交时报名早已成功，因此 ok=True。
    """

    ok: bool
    code: str
    message: str
    reason: str = ""
    next_step: str = ""
    status: str | None = None
    position: int | None = None
    retryable: bool = False
    token: str = ""

    # 兼容旧调用方：仍可按 (ok, message) 解包
    def __iter__(self):
        yield self.ok
        yield self.message


# ------------------------------------------------------------ 错误码
CODE_OK = "SIGNUP_OK"
CODE_PENDING = "SIGNUP_PENDING"
CODE_WAITLIST = "SIGNUP_WAITLIST"
CODE_ALREADY = "SIGNUP_ALREADY_REGISTERED"
CODE_CLOSED = "SIGNUP_CLOSED"
CODE_CANCELED = "SIGNUP_ACTIVITY_CANCELED"
CODE_ROLE = "SIGNUP_ROLE_NOT_ALLOWED"
CODE_INVALID_TOKEN = "SIGNUP_INVALID_TOKEN"
CODE_ERROR = "SIGNUP_SERVER_ERROR"


def _new_token() -> str:
    return uuid4().hex


def _record_attempt(token: str, user, activity, result: SignupResult) -> SignupResult:
    """把本次提交的结果写成幂等凭据；写失败不应影响报名本身。"""
    db.session.add(
        SignupAttempt(
            token=token,
            user_id=user.id,
            activity_id=activity.id,
            code=result.code,
            status=result.status,
            message=result.message[:255],
            reason=result.reason[:255],
            next_step=result.next_step[:255],
            position=result.position,
            retryable=result.retryable,
        )
    )
    return result


def _from_attempt(attempt: SignupAttempt) -> SignupResult:
    return SignupResult(
        ok=attempt.code
        in (CODE_OK, CODE_PENDING, CODE_WAITLIST, CODE_ALREADY),
        code=attempt.code,
        message=attempt.message,
        reason=attempt.reason,
        next_step=attempt.next_step,
        status=attempt.status,
        position=attempt.position,
        retryable=attempt.retryable,
        token=attempt.token,
    )


# ============================================================ 报名
def signup(activity, user, token: str | None = None):
    """学生报名活动，返回 SignupResult（R-10 / R-11 / R-12）。

    token 为空时生成一个——这样即使调用方（如旧测试、直接提交）没带令牌，
    结果仍然可以在结果页回看，且不会重复建记录。
    """
    token = (token or "").strip()
    if not TOKEN_PATTERN.match(token):
        token = _new_token()

    # ---- 幂等：同一 token 的重复提交直接返回首次结果（R-10）----
    attempt = SignupAttempt.query.filter_by(token=token).first()
    if attempt is not None:
        if attempt.user_id != user.id or attempt.activity_id != activity.id:
            return SignupResult(
                ok=False,
                code=CODE_INVALID_TOKEN,
                message="本次提交的凭据无效，请返回活动详情重新提交。",
                reason="提交凭据与当前账号或活动不匹配。",
                next_step="返回活动详情页后重新报名。",
                # 不返回 token：该令牌属于另一次提交，用它寻址结果页会读到别人的快照
                token="",
            )
        # 状态若在此期间发生了变化（如候补已被递补），以当前状态为准，
        # 避免把过期快照当成事实展示。
        current = activity.registration_of(user)
        if current is not None and current.status != attempt.status:
            return _already_result(activity, current, token)
        return _from_attempt(attempt)

    result = _do_signup(activity, user, token)

    # 只有真正走到业务判断的提交才记录；令牌非法等情况不落库
    if result.code != CODE_INVALID_TOKEN:
        _record_attempt(token, user, activity, result)

    try:
        db.session.commit()
    except Exception:  # pragma: no cover - 数据库异常路径由路由兜底
        db.session.rollback()
        return SignupResult(
            ok=False,
            code=CODE_ERROR,
            message="报名没有提交成功，请稍后重试。",
            reason="服务端在处理本次请求时发生异常。",
            next_step="等待几秒后再次点击提交；重复提交不会产生重复报名。",
            retryable=True,
            token=token,
        )

    return result


def _do_signup(activity, user, token: str) -> SignupResult:
    # 角色校验：教师与管理员的账号都不参与报名
    if user.role != ROLE_STUDENT:
        return SignupResult(
            ok=False,
            code=CODE_ROLE,
            message="只有学生账号可以报名活动。",
            reason="当前登录账号的角色是教师或管理员。",
            next_step="如需报名，请使用学生账号登录。",
            token=token,
        )

    # 活动必须处于可报名状态（已下架的活动不可报名）
    if activity.status == STATUS_CANCELED:
        return SignupResult(
            ok=False,
            code=CODE_CANCELED,
            message="该活动已下架，无法报名。",
            reason="活动已被组织教师或管理员下架。",
            next_step="返回活动列表，选择其他仍在报名的活动。",
            token=token,
        )

    # 报名截止校验（约束 C2）
    # 页面在截止后会隐藏报名按钮，但按钮隐藏只是体验，不能当作规则：
    # 直接向报名接口提交请求同样必须被拒绝。
    if now() > activity.signup_deadline:
        deadline_text = activity.signup_deadline.strftime("%Y-%m-%d %H:%M")
        return SignupResult(
            ok=False,
            code=CODE_CLOSED,
            message=f"该活动报名已截止（截止时间 {deadline_text}），无法报名。",
            reason=f"报名通道已于 {deadline_text} 关闭。",
            next_step="可以浏览其他仍在报名的活动。",
            token=token,
        )

    # 重复报名：不再当成错误（R-10）。用户想要的结果其实已经达成，
    # 只是需要一个明确的当前状态。
    existing = activity.registration_of(user)
    if existing is not None and existing.is_active:
        return _already_result(activity, existing, token)

    # 判定初始状态（R-04：先看活动是否需要审核；R-06：再看当时名额）
    if activity.requires_review:
        status = REG_PENDING
    elif activity.has_vacancy:
        status = REG_APPROVED
    else:
        # R-12：名额刚满不是失败，直接进入候补，位次随后计算
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
        # 并发提交被数据库拦下：说明另一条请求已经成功，按"已报名"处理，
        # 而不是告诉用户失败（R-10）。
        db.session.rollback()
        current = activity.registration_of(user)
        if current is not None:
            return _already_result(activity, current, token)
        return SignupResult(
            ok=False,
            code=CODE_ERROR,
            message="报名没有提交成功，请稍后重试。",
            reason="同一时间有多条相同请求，数据库只接受了其中一条。",
            next_step="刷新页面查看当前报名状态。",
            retryable=True,
            token=token,
        )

    position = None
    if registration.status == REG_WAITLIST:
        # 新建的记录是直接 add 到 session 的，activity.registrations 这个
        # 已加载的集合不会自动包含它；先让它失效，再按真实队列算位次。
        db.session.flush()
        db.session.expire(activity, ["registrations"])
        position = waitlist_position(activity, registration)

    result = _success_result(activity, registration, position, token)
    log_operation(
        user,
        action="signup_activity",
        target_type="activity",
        target_id=activity.id,
        detail=f"报名活动《{activity.title}》（{registration.status_label}）",
    )
    return result


def _success_result(activity, registration, position=None, token="") -> SignupResult:
    if registration.status == REG_PENDING:
        return SignupResult(
            ok=True,
            code=CODE_PENDING,
            message=f"报名申请已提交：《{activity.title}》。",
            reason="该活动需要组织教师审核，你的申请已进入待审核队列。",
            next_step="等待教师审核；结果会出现在「通知」里，无需反复刷新。",
            status=registration.status,
            token=token,
        )
    if registration.status == REG_WAITLIST:
        return SignupResult(
            ok=True,
            code=CODE_WAITLIST,
            message=f"已进入候补队列（当前第 {position} 位）：《{activity.title}》。",
            reason="你提交时名额已满，系统按提交时间把你排入候补。",
            next_step="有人取消时会自动补位并通知你，无需重复提交。",
            status=registration.status,
            position=position,
            token=token,
        )
    return SignupResult(
        ok=True,
        code=CODE_OK,
        message=f"报名成功：《{activity.title}》。",
        reason="当前仍有空余名额，你已被确认为正式参加。",
        next_step="请按活动时间与地点参加；如需取消，在「我的报名」中操作。",
        status=registration.status,
        token=token,
    )


def _already_result(activity, registration, token: str = "") -> SignupResult:
    """重复报名：返回当前状态，语义为成功（R-10）。"""
    submitted = (registration.created_at or now()).strftime("%Y-%m-%d %H:%M")
    position = registration.waitlist_position

    if registration.status == REG_PENDING:
        next_step = "等待教师审核，结果会出现在「通知」里。"
    elif registration.status == REG_WAITLIST:
        next_step = f"你当前在第 {position} 位，有人取消时会自动补位并通知你。"
    elif registration.status == REG_APPROVED:
        next_step = "你已被确认为正式参加，请按时到场；如需取消请在「我的报名」中操作。"
    elif registration.status == REG_REJECTED:
        next_step = "本次申请未通过，可查看活动详情确认是否符合参加资格。"
    else:
        next_step = "如需参加，可以在活动详情页重新报名。"

    return SignupResult(
        ok=True,
        code=CODE_ALREADY,
        message=f"你已于 {submitted} 提交过报名，当前状态：{registration.status_label}。",
        reason="系统检测到同一活动已有你的有效报名记录，本次提交不会重复占用名额。",
        next_step=next_step,
        status=registration.status,
        position=position,
        token=token,
    )


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
        # R-14：递补结果必须主动触达。数据里 32 人在递补后 72 小时内
        # 从未打开过状态页——通知就是为这件事加的。
        notify(
            promoted.user,
            NOTIFY_WAITLIST_PROMOTED,
            f"候补成功：《{activity.title}》",
            "你已从候补转为正式参加，请按活动时间与地点到场。",
            activity_id=activity.id,
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
    V3.0：审核结果同时写入学生通知（R-14）。
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
        notify(
            registration.user,
            NOTIFY_REVIEW_REJECTED,
            f"报名未通过：《{activity.title}》",
            "组织教师未通过你的报名申请。如需了解原因，请联系活动组织教师。",
            activity_id=activity.id,
        )
        db.session.commit()
        return True, f"已拒绝 {name} 的报名申请。"

    # 通过 → 再看当时名额（R-06 的顺序：先资格、后名额）
    if activity.has_vacancy:
        registration.status = REG_APPROVED
        registration.waitlisted_at = None
        tail = "已确认为正式参加。"
        title = f"报名已通过：《{activity.title}》"
        body = "你已被确认为正式参加，请按活动时间与地点到场。"
    else:
        registration.status = REG_WAITLIST
        # 此刻才真正进入候补队列——候补排序以该时刻为准（访谈规则，D10 修订）
        registration.waitlisted_at = now()
        position = waitlist_position(activity, registration)
        tail = "当时名额已满，已转入候补队列（按进入候补的时间排队）。"
        title = f"报名已通过，转入候补：《{activity.title}》"
        body = f"审核通过时名额已满，你当前排在候补第 {position} 位，有人取消时会自动补位。"
    registration.decided_at = now()

    log_operation(
        reviewer, action="review_approve", target_type="activity",
        target_id=activity.id,
        detail=f"通过 {name} 报名《{activity.title}》（{registration.status_label}）",
    )
    notify(
        registration.user,
        NOTIFY_REVIEW_APPROVED,
        title,
        body,
        activity_id=activity.id,
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


def active_registrants(activity):
    """当前仍有效的报名者（待审核／已通过／候补中），用于活动下架通知。"""
    return [r.user for r in activity.registrations if r.status in REG_ACTIVE]

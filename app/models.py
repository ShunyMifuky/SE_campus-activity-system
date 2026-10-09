"""数据模型与业务状态、角色的集中定义。

对应需求：
  REQ-01 用户与身份（User）
  REQ-03 活动（Category / Activity）
  REQ-05 报名（Registration）
  REQ-06 报名名单（依赖 Registration）

重要约束（工程意图 C1）：User.password_hash 只保存哈希值，
明文密码不落库、不入日志、不写入模板上下文。
"""

from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db, login_manager

# ---------------------------------------------------------------- 角色
ROLE_STUDENT = "student"
ROLE_TEACHER = "teacher"
ROLE_ADMIN = "admin"          # V2.0 新增（R-09：平台账号与活动秩序的管理者）

ROLE_LABELS = {
    ROLE_STUDENT: "学生",
    ROLE_TEACHER: "活动组织教师",
    ROLE_ADMIN: "系统管理员",
}

# ------------------------------------------------- 活动状态（约束 C4）
# 这些值不写入数据库，而是由 Activity.status 依据当前时间与各时间字段推导，
# 避免出现"状态字段与真实时间不一致"的脏数据。
STATUS_OPEN = "open"           # 报名中
STATUS_CLOSED = "closed"       # 报名已截止，活动未开始
STATUS_ONGOING = "ongoing"     # 进行中
STATUS_FINISHED = "finished"   # 已结束
STATUS_CANCELED = "canceled"   # 已下架

STATUS_LABELS = {
    STATUS_OPEN: "报名中",
    STATUS_CLOSED: "报名已截止",
    STATUS_ONGOING: "进行中",
    STATUS_FINISHED: "已结束",
    STATUS_CANCELED: "已下架",
}

# 可以作为筛选条件的活动状态（列表页使用）
FILTERABLE_STATUSES = [STATUS_OPEN, STATUS_CLOSED, STATUS_ONGOING, STATUS_FINISHED, STATUS_CANCELED]

# ------------------------------------------------- 报名状态（V2.0 新增）
# 与活动状态不同：报名状态由**事件**驱动（教师审核、他人取消触发递补），
# 无法由时间推导，因此落库为显式字段（设计决策 D6）。
REG_PENDING = "pending"        # 待审核：活动设为「需要审核」时的初始状态
REG_APPROVED = "approved"      # 已通过：正式参加，占用名额
REG_WAITLIST = "waitlist"      # 候补中：等待他人释放位置
REG_REJECTED = "rejected"      # 审核未通过
REG_CANCELED = "canceled"      # 已取消：放弃报名或退出候补

REG_LABELS = {
    REG_PENDING: "待审核",
    REG_APPROVED: "已通过",
    REG_WAITLIST: "候补中",
    REG_REJECTED: "未通过",
    REG_CANCELED: "已取消",
}

# 占用正式名额的状态（设计决策 D7：只有「已通过」占名额）
REG_OCCUPYING = (REG_APPROVED,)

# 仍算「有效报名」的状态——用于判断是否重复报名。
# 已取消与未通过不算有效，学生可以重新报名（复用同一条记录，见设计决策 D9）。
REG_ACTIVE = (REG_PENDING, REG_APPROVED, REG_WAITLIST)


def now():
    """统一时间口径：本地时间、精确到秒。

    全项目只通过本函数取当前时间，避免各模块口径不一致导致
    报名截止、活动状态判断出现分歧。
    """
    return datetime.now().replace(microsecond=0)


class User(UserMixin, db.Model):
    """用户：学生与活动组织教师共用一张表，用 role 区分。"""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    real_name = db.Column(db.String(50), nullable=False)
    # 学生填学号，教师填工号，仅用于报名名单展示
    student_no = db.Column(db.String(30), nullable=False, default="")
    role = db.Column(db.String(20), nullable=False, default=ROLE_STUDENT, index=True)
    # 账号是否可用。系统管理员可将异常账号停用（R-09）；
    # 停用只影响登录，不改变该用户已有的报名记录。
    enabled = db.Column(db.Boolean, nullable=False, default=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=now)

    created_activities = db.relationship(
        "Activity", back_populates="creator", cascade="all, delete-orphan"
    )
    registrations = db.relationship(
        "Registration", back_populates="user", cascade="all, delete-orphan"
    )

    # -------------------------------------------------- 密码（约束 C1）
    def set_password(self, raw_password: str) -> None:
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password_hash, raw_password)

    # ------------------------------------------------------------ 角色
    @property
    def is_teacher(self) -> bool:
        return self.role == ROLE_TEACHER

    @property
    def is_student(self) -> bool:
        return self.role == ROLE_STUDENT

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    # -------------------------------------------------------- 账号状态
    @property
    def is_active(self) -> bool:
        """覆盖 UserMixin 的默认实现（设计决策 D8）。

        Flask-Login 在登录校验与 login_required 检查时都会读这个属性，
        因此停用账号在这里返回 False，即可在**所有入口**统一生效，
        不必逐处手写判断、避免遗漏。
        """
        return bool(self.enabled)

    @property
    def role_label(self) -> str:
        return ROLE_LABELS.get(self.role, self.role)

    def __repr__(self) -> str:
        # 注意：刻意不输出任何与密码相关的字段
        return f"<User {self.username} role={self.role}>"


class Category(db.Model):
    """活动分类：讲座报告 / 文体活动 / 志愿服务 / 社团活动 / 科技竞赛。"""

    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(30), unique=True, nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    activities = db.relationship("Activity", back_populates="category")

    def __repr__(self) -> str:
        return f"<Category {self.name}>"


class Activity(db.Model):
    """校园活动。"""

    __tablename__ = "activities"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    summary = db.Column(db.String(500), nullable=False, default="")
    location = db.Column(db.String(120), nullable=False, default="")

    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    # 报名截止时间（约束 C2 的校验依据之一）
    signup_deadline = db.Column(db.DateTime, nullable=False)
    # 人数上限，0 表示不限
    capacity = db.Column(db.Integer, nullable=False, default=0)

    # ---- V2.0 新增：审核开关（R-04）与参加资格（R-08）----
    # 是否需要教师逐个审核报名。默认 False：保持 V1.0 行为不变，
    # 不给存量活动凭空增加一道等待。
    requires_review = db.Column(db.Boolean, nullable=False, default=False, index=True)
    # 参加资格条件说明（可选，仅作展示与审核依据，系统不做自动筛选）
    eligibility_note = db.Column(db.String(200), nullable=False, default="")

    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"))
    creator_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    # 非空表示已被教师或管理员下架（软下架，保留历史记录与报名数据）
    canceled_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=now)
    updated_at = db.Column(db.DateTime, nullable=False, default=now, onupdate=now)

    category = db.relationship("Category", back_populates="activities")
    creator = db.relationship("User", back_populates="created_activities")
    registrations = db.relationship(
        "Registration", back_populates="activity", cascade="all, delete-orphan"
    )

    # ------------------------------------------------- 状态与名额（约束 C4）
    @property
    def status(self) -> str:
        """由时间与下架标记推导活动状态，不依赖任何可写字段。"""
        if self.canceled_at is not None:
            return STATUS_CANCELED
        current = now()
        if current < self.start_time:
            return STATUS_OPEN if current <= self.signup_deadline else STATUS_CLOSED
        if current <= self.end_time:
            return STATUS_ONGOING
        return STATUS_FINISHED

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)

    # ------------------------------------------------- 名额口径（设计决策 D7）
    # V2.0 起：只有「已通过」的记录占用名额；待审核与候补中的都不占。
    @property
    def approved_count(self) -> int:
        return sum(1 for r in self.registrations if r.status == REG_APPROVED)

    @property
    def waitlist_count(self) -> int:
        return sum(1 for r in self.registrations if r.status == REG_WAITLIST)

    @property
    def pending_count(self) -> int:
        return sum(1 for r in self.registrations if r.status == REG_PENDING)

    @property
    def registered_count(self) -> int:
        """正式参加人数（沿用 V1.0 属性名，口径已按 D7 收紧）。"""
        return self.approved_count

    @property
    def remaining(self):
        """剩余名额；不限人数时返回 None。"""
        if not self.capacity:
            return None
        return max(self.capacity - self.approved_count, 0)

    @property
    def has_vacancy(self) -> bool:
        """是否还有空位（人数不限时恒为 True）。"""
        return not self.capacity or self.approved_count < self.capacity

    @property
    def is_full(self) -> bool:
        return not self.has_vacancy

    @property
    def waitlist_ordered(self):
        """候补队列：按报名记录创建时间升序（设计决策 D10）。

        不另建队列表——创建时间天然稳定；且审核后转入候补的人沿用其原始
        报名时间，不会因为"转得晚"而排到后面。
        """
        return sorted(
            (r for r in self.registrations if r.status == REG_WAITLIST),
            key=lambda r: (r.created_at, r.id),
        )

    @property
    def is_signup_open(self) -> bool:
        """是否处于报名期内（未截止、未下架）。

        V2.0 起满员不再阻挡提交——满员时提交会进入候补，
        因此本属性只表示"报名通道是否还开着"。
        """
        return self.status == STATUS_OPEN

    @property
    def capacity_label(self) -> str:
        return "不限" if not self.capacity else str(self.capacity)

    def has_registration_of(self, user) -> bool:
        """该用户是否已有**有效**报名（待审核／已通过／候补中）。

        已取消与未通过的记录不算有效，学生可以重新报名（复用同一条记录）。
        """
        if not getattr(user, "is_authenticated", False):
            return False
        return any(
            r.user_id == user.id and r.status in REG_ACTIVE for r in self.registrations
        )

    def registration_of(self, user):
        """取该用户在本人活动上的报名记录（不论状态），没有则返回 None。"""
        uid = getattr(user, "id", None)
        if uid is None:
            return None
        for r in self.registrations:
            if r.user_id == uid:
                return r
        return None

    def __repr__(self) -> str:
        return f"<Activity {self.id} {self.title}>"


class Registration(db.Model):
    """报名记录。

    (activity_id, user_id) 上加唯一约束——这是防止重复报名的**最终防线**：
    应用层校验可能因并发提交或重复点击而失效，数据库约束不会。
    """

    __tablename__ = "registrations"
    __table_args__ = (
        db.UniqueConstraint("activity_id", "user_id", name="uq_registration_activity_user"),
    )

    id = db.Column(db.Integer, primary_key=True)
    activity_id = db.Column(db.Integer, db.ForeignKey("activities.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    # 报名状态（设计决策 D6）。
    # 不改动上面的唯一约束——一活动一学生仍只有一条记录；
    # 取消后重新报名时复用这条记录（设计决策 D9）。
    status = db.Column(db.String(20), nullable=False, default=REG_APPROVED, index=True)
    # 状态最近一次变化的时间（审核、递补等），用于名单展示与问题排查
    decided_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=now)

    activity = db.relationship("Activity", back_populates="registrations")
    user = db.relationship("User", back_populates="registrations")

    # ------------------------------------------------------------ 状态
    @property
    def status_label(self) -> str:
        return REG_LABELS.get(self.status, self.status)

    @property
    def is_active(self) -> bool:
        """是否仍算有效报名（用于重复报名判断）。"""
        return self.status in REG_ACTIVE

    @property
    def occupies_slot(self) -> bool:
        """是否占用正式名额。"""
        return self.status in REG_OCCUPYING

    @property
    def waitlist_position(self):
        """在当前活动候补队列中的位次（从 1 开始）；不在队列中返回 None。"""
        if self.status != REG_WAITLIST:
            return None
        for index, item in enumerate(self.activity.waitlist_ordered, start=1):
            if item.id == self.id:
                return index
        return None

    def __repr__(self) -> str:
        return (
            f"<Registration activity={self.activity_id} user={self.user_id} "
            f"status={self.status}>"
        )


class OperationLog(db.Model):
    """关键操作日志：发布 / 下架 / 报名 / 取消报名。

    作用是让"谁在什么时候对哪个对象做了什么"可追溯，
    支撑报告要求的"需求—设计—实现—验证可对应"。
    """

    __tablename__ = "operation_logs"

    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    action = db.Column(db.String(40), nullable=False)
    target_type = db.Column(db.String(40), nullable=False)
    target_id = db.Column(db.Integer)
    detail = db.Column(db.String(255), nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=now)

    actor = db.relationship("User")

    def __repr__(self) -> str:
        return f"<OperationLog {self.action} target={self.target_type}:{self.target_id}>"


def log_operation(actor, action: str, target_type: str, target_id=None, detail: str = "") -> None:
    """写入一条操作日志（由调用方负责 commit）。"""
    db.session.add(
        OperationLog(
            actor_id=actor.id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail[:255],
        )
    )


@login_manager.user_loader
def load_user(user_id: str):
    return db.session.get(User, int(user_id))

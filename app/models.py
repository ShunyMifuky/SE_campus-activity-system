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

ROLE_LABELS = {
    ROLE_STUDENT: "学生",
    ROLE_TEACHER: "活动组织教师",
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

    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"))
    creator_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    # 非空表示已被教师下架（软下架，保留历史记录与报名数据）
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

    @property
    def registered_count(self) -> int:
        return len(self.registrations)

    @property
    def remaining(self):
        """剩余名额；不限人数时返回 None。"""
        if not self.capacity:
            return None
        return max(self.capacity - self.registered_count, 0)

    @property
    def is_full(self) -> bool:
        return bool(self.capacity) and self.registered_count >= self.capacity

    @property
    def is_signup_open(self) -> bool:
        """是否处于"可报名"状态：报名中且未满员。"""
        return self.status == STATUS_OPEN and not self.is_full

    @property
    def capacity_label(self) -> str:
        return "不限" if not self.capacity else str(self.capacity)

    def has_registration_of(self, user) -> bool:
        if not getattr(user, "is_authenticated", False):
            return False
        return any(r.user_id == user.id for r in self.registrations)

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
    created_at = db.Column(db.DateTime, nullable=False, default=now)

    activity = db.relationship("Activity", back_populates="registrations")
    user = db.relationship("User", back_populates="registrations")

    def __repr__(self) -> str:
        return f"<Registration activity={self.activity_id} user={self.user_id}>"


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

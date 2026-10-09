"""V2.0 验证用例：基于用户访谈演化出的新规则 + V1.0 核心流程回归。

每条用例对应 docs/05-V2.0需求演化.md 中的需求编号（R-xx）与
docs/06-V2.0设计调整.md 中的设计决策（D-xx）。

验证方式沿用 V1.0 的约定：
  - 只通过 HTTP 接口验证，走用户真实能走通的路径，不直接调 service 内部函数
  - 每条用例使用独立的临时数据库，用例之间互不影响
  - 不在用例期间长期持有 app context（否则 Flask-Login 的 current_user 会串号）
"""

import os
import tempfile
import time
import unittest
from datetime import timedelta

from app import create_app
from app.extensions import db
from app.models import (
    REG_APPROVED,
    REG_CANCELED,
    REG_PENDING,
    REG_REJECTED,
    REG_WAITLIST,
    ROLE_ADMIN,
    ROLE_STUDENT,
    ROLE_TEACHER,
    Activity,
    Registration,
    User,
    now,
)

PASSWORD = "Demo@2026"


class BaseCase(unittest.TestCase):
    """公共脚手架：临时库 + 三类账号 + 便捷方法。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        db_path = os.path.join(self._tmp.name, "test.db")

        class Cfg:
            SECRET_KEY = "test-secret"
            SQLALCHEMY_DATABASE_URI = "sqlite:///" + db_path
            SQLALCHEMY_TRACK_MODIFICATIONS = False

        self.app = create_app(Cfg)
        with self.app.app_context():
            db.create_all()
            self._seed_accounts()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()  # 释放 sqlite 文件句柄，否则 Windows 上删不掉临时库
        self._tmp.cleanup()

    def _seed_accounts(self):
        accounts = [
            ("teacher", "王老师", ROLE_TEACHER, "T001"),
            ("teacher2", "李老师", ROLE_TEACHER, "T002"),
            ("admin", "平台管理员", ROLE_ADMIN, ""),
            ("stu1", "学生一", ROLE_STUDENT, "2023001"),
            ("stu2", "学生二", ROLE_STUDENT, "2023002"),
            ("stu3", "学生三", ROLE_STUDENT, "2023003"),
        ]
        for username, name, role, no in accounts:
            user = User(username=username, real_name=name, role=role, student_no=no)
            user.set_password(PASSWORD)
            db.session.add(user)
        db.session.commit()

    # ---------------------------------------------------------- 便捷方法
    def client(self):
        return self.app.test_client()

    def login(self, client, username, password=PASSWORD):
        return client.post(
            "/auth/login",
            data={"username": username, "password": password},
            follow_redirects=True,
        )

    def make_activity(self, creator="teacher", capacity=2, requires_review=False,
                      eligibility="", start_days=5, deadline_days=4):
        """直接建活动，聚焦报名规则本身（活动表单另有用例覆盖）。"""
        with self.app.app_context():
            owner = User.query.filter_by(username=creator).first()
            base = now()
            activity = Activity(
                title=f"活动-{creator}-cap{capacity}-rev{int(requires_review)}",
                summary="用例用活动",
                location="测试地点",
                start_time=base + timedelta(days=start_days),
                end_time=base + timedelta(days=start_days, hours=2),
                signup_deadline=base + timedelta(days=deadline_days),
                capacity=capacity,
                creator_id=owner.id,
                requires_review=requires_review,
                eligibility_note=eligibility,
            )
            db.session.add(activity)
            db.session.commit()
            return activity.id

    def reg_status(self, activity_id, username):
        with self.app.app_context():
            user = User.query.filter_by(username=username).first()
            reg = Registration.query.filter_by(
                activity_id=activity_id, user_id=user.id
            ).first()
            return reg.status if reg else None

    def reg_id(self, activity_id, username):
        with self.app.app_context():
            user = User.query.filter_by(username=username).first()
            reg = Registration.query.filter_by(
                activity_id=activity_id, user_id=user.id
            ).first()
            return reg.id if reg else None

    def approved_count(self, activity_id):
        with self.app.app_context():
            activity = db.session.get(Activity, activity_id)
            return activity.approved_count


# ==================================================================== R-01
class WaitlistSignupCase(BaseCase):
    """R-01：满员后仍可提交，进入候补队列。"""

    def test_01_full_activity_enters_waitlist(self):
        """TEST-V2-01：名额已满时提交 → 进入候补（不再直接拒绝）。"""
        aid = self.make_activity(capacity=1)
        c1 = self.client()
        self.login(c1, "stu1")
        self.assertIn("报名成功", c1.post(f"/activities/{aid}/signup", follow_redirects=True).get_data(as_text=True))
        self.assertEqual(self.reg_status(aid, "stu1"), REG_APPROVED)

        c2 = self.client()
        self.login(c2, "stu2")
        body = c2.post(f"/activities/{aid}/signup", follow_redirects=True).get_data(as_text=True)
        self.assertIn("候补", body)
        self.assertEqual(self.reg_status(aid, "stu2"), REG_WAITLIST)
        self.assertEqual(self.approved_count(aid), 1)   # 候补不占名额（D7）

    def test_02_waitlist_order_follows_signup_time(self):
        """TEST-V2-02：候补顺序按进入候补的时间先后（R-01 核心规则）。"""
        aid = self.make_activity(capacity=1)
        c0 = self.client()
        self.login(c0, "stu1")
        c0.post(f"/activities/{aid}/signup", follow_redirects=True)

        for name in ("stu2", "stu3"):
            c = self.client()
            self.login(c, name)
            c.post(f"/activities/{aid}/signup", follow_redirects=True)

        with self.app.app_context():
            activity = db.session.get(Activity, aid)
            order = [r.user.username for r in activity.waitlist_ordered]
        self.assertEqual(order, ["stu2", "stu3"], "候补应按提交时间升序")

    def test_03_unlimited_capacity_never_waitlists(self):
        """TEST-V2-03（边界）：人数不限的活动永不满员，直接正式参加。"""
        aid = self.make_activity(capacity=0)
        for name in ("stu1", "stu2", "stu3"):
            c = self.client()
            self.login(c, name)
            c.post(f"/activities/{aid}/signup", follow_redirects=True)
        self.assertEqual(self.approved_count(aid), 3)
        self.assertEqual(self.reg_status(aid, "stu3"), REG_APPROVED)

    def test_04_duplicate_waitlist_rejected(self):
        """TEST-V2-04（异常）：已在候补中再次提交 → 被拒绝。"""
        aid = self.make_activity(capacity=1)
        c1 = self.client()
        self.login(c1, "stu1")
        c1.post(f"/activities/{aid}/signup", follow_redirects=True)

        c2 = self.client()
        self.login(c2, "stu2")
        c2.post(f"/activities/{aid}/signup", follow_redirects=True)
        body = c2.post(f"/activities/{aid}/signup", follow_redirects=True).get_data(as_text=True)
        self.assertIn("候补队列中", body)

        with self.app.app_context():
            count = Registration.query.filter_by(activity_id=aid).count()
        self.assertEqual(count, 2, "同一活动同一学生只应有一条记录")


# ==================================================================== R-02
class PromotionCase(BaseCase):
    """R-02：空位释放后自动递补给候补最靠前者（设计决策 D11：同一事务内完成）。"""

    def test_05_cancel_triggers_auto_promotion(self):
        """TEST-V2-05：正式参加者取消 → 候补第一位自动补上。"""
        aid = self.make_activity(capacity=1)
        c1 = self.client()
        self.login(c1, "stu1")
        c1.post(f"/activities/{aid}/signup", follow_redirects=True)

        c2 = self.client()
        self.login(c2, "stu2")
        c2.post(f"/activities/{aid}/signup", follow_redirects=True)

        body = c1.post(f"/activities/{aid}/cancel-signup", follow_redirects=True).get_data(as_text=True)
        self.assertIn("已取消报名", body)
        self.assertIn("学生二", body, "应提示已自动补给候补第一位")
        self.assertEqual(self.reg_status(aid, "stu2"), REG_APPROVED, "候补第一位应自动转为正式参加")
        self.assertEqual(self.reg_status(aid, "stu1"), REG_CANCELED)
        self.assertEqual(self.approved_count(aid), 1)

    def test_06_promotion_picks_earliest_waitlist(self):
        """TEST-V2-06：多人候补时，补给顺序最靠前者而非任意一人。"""
        aid = self.make_activity(capacity=1)
        c1 = self.client()
        self.login(c1, "stu1")
        c1.post(f"/activities/{aid}/signup", follow_redirects=True)

        for name in ("stu2", "stu3"):
            c = self.client()
            self.login(c, name)
            c.post(f"/activities/{aid}/signup", follow_redirects=True)

        c1.post(f"/activities/{aid}/cancel-signup", follow_redirects=True)
        self.assertEqual(self.reg_status(aid, "stu2"), REG_APPROVED)
        self.assertEqual(self.reg_status(aid, "stu3"), REG_WAITLIST)

    def test_07_empty_waitlist_keeps_vacancy(self):
        """TEST-V2-07（异常）：无人候补时取消 → 位置保持空缺，不报错。"""
        aid = self.make_activity(capacity=2)
        c1 = self.client()
        self.login(c1, "stu1")
        c1.post(f"/activities/{aid}/signup", follow_redirects=True)

        body = c1.post(f"/activities/{aid}/cancel-signup", follow_redirects=True).get_data(as_text=True)
        self.assertIn("已取消报名", body)
        self.assertEqual(self.approved_count(aid), 0)

    def test_08_promotion_only_fills_real_vacancy(self):
        """TEST-V2-08（边界）：取消后若名额仍满（人数不限场景）不误触发递补。"""
        aid = self.make_activity(capacity=0)      # 人数不限 → 不存在空位概念
        c1 = self.client()
        self.login(c1, "stu1")
        c1.post(f"/activities/{aid}/signup", follow_redirects=True)

        c2 = self.client()
        self.login(c2, "stu2")
        c2.post(f"/activities/{aid}/signup", follow_redirects=True)

        c1.post(f"/activities/{aid}/cancel-signup", follow_redirects=True)
        self.assertEqual(self.reg_status(aid, "stu2"), REG_APPROVED, "人数不限时不应把他人改成候补")


# ==================================================================== R-03
class WaitlistExitCase(BaseCase):
    """R-03：候补可主动退出，其后人员依序前移；退出不释放正式名额。"""

    def test_09_exit_waitlist_and_reorder(self):
        """TEST-V2-09：候补者退出后，其身后的人依序前移。"""
        aid = self.make_activity(capacity=1)
        c1 = self.client()
        self.login(c1, "stu1")
        c1.post(f"/activities/{aid}/signup", follow_redirects=True)

        for name in ("stu2", "stu3"):
            c = self.client()
            self.login(c, name)
            c.post(f"/activities/{aid}/signup", follow_redirects=True)

        c2 = self.client()
        self.login(c2, "stu2")
        body = c2.post(f"/activities/{aid}/exit-waitlist", follow_redirects=True).get_data(as_text=True)
        self.assertIn("已退出候补", body)
        self.assertEqual(self.reg_status(aid, "stu2"), REG_CANCELED)

        with self.app.app_context():
            activity = db.session.get(Activity, aid)
            order = [r.user.username for r in activity.waitlist_ordered]
        self.assertEqual(order, ["stu3"], "候补队列应只剩学生三")

    def test_10_exit_waitlist_does_not_promote(self):
        """TEST-V2-10（边界）：退出候补不释放正式名额，因此不触发递补。"""
        aid = self.make_activity(capacity=1)
        c1 = self.client()
        self.login(c1, "stu1")
        c1.post(f"/activities/{aid}/signup", follow_redirects=True)

        c2 = self.client()
        self.login(c2, "stu2")
        c2.post(f"/activities/{aid}/signup", follow_redirects=True)

        c3 = self.client()
        self.login(c3, "stu3")
        c3.post(f"/activities/{aid}/signup", follow_redirects=True)

        c2.post(f"/activities/{aid}/exit-waitlist", follow_redirects=True)
        self.assertEqual(self.reg_status(aid, "stu1"), REG_APPROVED, "正式参加者不应受影响")
        self.assertEqual(self.reg_status(aid, "stu3"), REG_WAITLIST, "学生三仍在候补，不应被自动补位")

    def test_11_exit_waitlist_rejects_non_waitlist(self):
        """TEST-V2-11（异常）：正式参加者走"退出候补"入口 → 被拒绝，语义不混用。"""
        aid = self.make_activity(capacity=2)
        c1 = self.client()
        self.login(c1, "stu1")
        c1.post(f"/activities/{aid}/signup", follow_redirects=True)

        body = c1.post(f"/activities/{aid}/exit-waitlist", follow_redirects=True).get_data(as_text=True)
        self.assertIn("无法退出候补", body)
        self.assertEqual(self.reg_status(aid, "stu1"), REG_APPROVED)


# ================================================================= R-04~R-08
class ReviewCase(BaseCase):
    """R-04 审核开关、R-05 审核动作、R-06 先资格后名额、R-08 参加资格。"""

    def test_12_review_required_activity_pends(self):
        """TEST-V2-12：需审核的活动报名后进入「待审核」，且不占名额。"""
        aid = self.make_activity(capacity=2, requires_review=True, eligibility="限大三")
        c1 = self.client()
        self.login(c1, "stu1")
        body = c1.post(f"/activities/{aid}/signup", follow_redirects=True).get_data(as_text=True)
        self.assertIn("等待", body)
        self.assertEqual(self.reg_status(aid, "stu1"), REG_PENDING)
        self.assertEqual(self.approved_count(aid), 0, "待审核不占名额（D7）")

    def test_13_no_review_activity_takes_effect_directly(self):
        """TEST-V2-13（回归）：未开启审核的活动报名后直接生效，与 V1.0 一致。"""
        aid = self.make_activity(capacity=2, requires_review=False)
        c1 = self.client()
        self.login(c1, "stu1")
        body = c1.post(f"/activities/{aid}/signup", follow_redirects=True).get_data(as_text=True)
        self.assertIn("报名成功", body)
        self.assertEqual(self.reg_status(aid, "stu1"), REG_APPROVED)

    def test_14_approve_with_vacancy_becomes_approved(self):
        """TEST-V2-14：审核通过且有名额 → 正式参加。"""
        aid = self.make_activity(capacity=2, requires_review=True)
        c1 = self.client()
        self.login(c1, "stu1")
        c1.post(f"/activities/{aid}/signup", follow_redirects=True)
        rid = self.reg_id(aid, "stu1")

        t = self.client()
        self.login(t, "teacher")
        body = t.post(
            f"/activities/{aid}/registrations/{rid}/review",
            data={"decision": "approve"}, follow_redirects=True,
        ).get_data(as_text=True)
        self.assertIn("已通过", body)
        self.assertEqual(self.reg_status(aid, "stu1"), REG_APPROVED)

    def test_15_approve_without_vacancy_goes_waitlist(self):
        """TEST-V2-15（R-06 核心）：先确认资格、通过后看名额——无名额则转入候补。"""
        aid = self.make_activity(capacity=1, requires_review=True)
        # 先让 stu1 报名并通过，占满唯一名额
        c1 = self.client()
        self.login(c1, "stu1")
        c1.post(f"/activities/{aid}/signup", follow_redirects=True)
        rid1 = self.reg_id(aid, "stu1")
        t = self.client()
        self.login(t, "teacher")
        t.post(f"/activities/{aid}/registrations/{rid1}/review",
               data={"decision": "approve"}, follow_redirects=True)
        self.assertEqual(self.approved_count(aid), 1)

        # 再让 stu2 报名并通过 —— 此时已无名额
        c2 = self.client()
        self.login(c2, "stu2")
        c2.post(f"/activities/{aid}/signup", follow_redirects=True)
        rid2 = self.reg_id(aid, "stu2")
        body = t.post(f"/activities/{aid}/registrations/{rid2}/review",
                      data={"decision": "approve"}, follow_redirects=True).get_data(as_text=True)
        self.assertIn("候补", body)
        self.assertEqual(self.reg_status(aid, "stu2"), REG_WAITLIST)
        self.assertEqual(self.approved_count(aid), 1, "通过但无名额时不应超额")

    def test_15b_waitlist_order_follows_enter_time(self):
        """TEST-V2-15b（D10 修订）：候补按「进入候补的时间」排序，而非报名时间。

        审核顺序与报名顺序相反时会分叉：先报名但后通过的人，是后进入候补的，
        应排在后面。
        """
        aid = self.make_activity(capacity=1, requires_review=True)

        # stu1 先报名并通过，占满唯一名额
        c1 = self.client()
        self.login(c1, "stu1")
        c1.post(f"/activities/{aid}/signup", follow_redirects=True)
        t = self.client()
        self.login(t, "teacher")
        t.post(
            f"/activities/{aid}/registrations/{self.reg_id(aid, 'stu1')}/review",
            data={"decision": "approve"}, follow_redirects=True,
        )
        self.assertEqual(self.approved_count(aid), 1)

        # stu2 较早报名、stu3 较晚报名（都处于待审核）
        c2 = self.client()
        self.login(c2, "stu2")
        c2.post(f"/activities/{aid}/signup", follow_redirects=True)
        c3 = self.client()
        self.login(c3, "stu3")
        c3.post(f"/activities/{aid}/signup", follow_redirects=True)
        rid2 = self.reg_id(aid, "stu2")
        rid3 = self.reg_id(aid, "stu3")

        # 先审核较晚报名的 stu3 → 无名额 → stu3 先进入候补
        t.post(f"/activities/{aid}/registrations/{rid3}/review",
               data={"decision": "approve"}, follow_redirects=True)
        # now() 只精确到秒，拉开 1 秒才能让两次入队时刻真正可区分
        time.sleep(1.05)
        # 再审核较早报名的 stu2 → stu2 后进入候补
        t.post(f"/activities/{aid}/registrations/{rid2}/review",
               data={"decision": "approve"}, follow_redirects=True)

        self.assertEqual(self.reg_status(aid, "stu2"), REG_WAITLIST)
        self.assertEqual(self.reg_status(aid, "stu3"), REG_WAITLIST)

        with self.app.app_context():
            activity = db.session.get(Activity, aid)
            order = [r.user.real_name for r in activity.waitlist_ordered]
        # stu3 先进入候补 → 应排在 stu2 前面（按报名时间会得到相反结果）
        self.assertEqual(order, ["学生三", "学生二"],
                         "候补应按进入候补的时间排序，而不是报名时间")

    def test_16_reject_keeps_no_slot(self):
        """TEST-V2-16：审核拒绝 → 未通过，不占名额也不进候补。"""
        aid = self.make_activity(capacity=2, requires_review=True)
        c1 = self.client()
        self.login(c1, "stu1")
        c1.post(f"/activities/{aid}/signup", follow_redirects=True)
        rid = self.reg_id(aid, "stu1")

        t = self.client()
        self.login(t, "teacher")
        body = t.post(f"/activities/{aid}/registrations/{rid}/review",
                      data={"decision": "reject"}, follow_redirects=True).get_data(as_text=True)
        self.assertIn("已拒绝", body)
        self.assertEqual(self.reg_status(aid, "stu1"), REG_REJECTED)
        self.assertEqual(self.approved_count(aid), 0)

    def test_17_only_pending_can_be_reviewed(self):
        """TEST-V2-17（异常）：已处理的申请不能重复审核。"""
        aid = self.make_activity(capacity=2, requires_review=True)
        c1 = self.client()
        self.login(c1, "stu1")
        c1.post(f"/activities/{aid}/signup", follow_redirects=True)
        rid = self.reg_id(aid, "stu1")

        t = self.client()
        self.login(t, "teacher")
        t.post(f"/activities/{aid}/registrations/{rid}/review",
               data={"decision": "approve"}, follow_redirects=True)
        body = t.post(f"/activities/{aid}/registrations/{rid}/review",
                      data={"decision": "reject"}, follow_redirects=True).get_data(as_text=True)
        self.assertIn("无法审核", body)
        self.assertEqual(self.reg_status(aid, "stu1"), REG_APPROVED)

    def test_18_teacher_cannot_review_other_activity(self):
        """TEST-V2-18（权限边界）：教师只能审核本人负责的活动。"""
        aid = self.make_activity(creator="teacher", capacity=2, requires_review=True)
        c1 = self.client()
        self.login(c1, "stu1")
        c1.post(f"/activities/{aid}/signup", follow_redirects=True)
        rid = self.reg_id(aid, "stu1")

        other = self.client()
        self.login(other, "teacher2")
        resp = other.post(f"/activities/{aid}/registrations/{rid}/review",
                          data={"decision": "approve"}, follow_redirects=False)
        self.assertEqual(resp.status_code, 403, "非本人活动应被拒绝")

    def test_19_student_cannot_review(self):
        """TEST-V2-19（权限边界）：学生不能执行审核动作。"""
        aid = self.make_activity(capacity=2, requires_review=True)
        c1 = self.client()
        self.login(c1, "stu1")
        c1.post(f"/activities/{aid}/signup", follow_redirects=True)
        rid = self.reg_id(aid, "stu1")

        resp = c1.post(f"/activities/{aid}/registrations/{rid}/review",
                       data={"decision": "approve"}, follow_redirects=False)
        self.assertEqual(resp.status_code, 403)

    def test_20_eligibility_note_shown_on_detail(self):
        """TEST-V2-20（R-08）：参加资格条件在活动详情页对学生可见。"""
        aid = self.make_activity(capacity=5, requires_review=True, eligibility="限大三及以上")
        c1 = self.client()
        self.login(c1, "stu1")
        body = c1.get(f"/activities/{aid}").get_data(as_text=True)
        self.assertIn("限大三及以上", body)


# ==================================================================== R-07
class StatusVisibilityCase(BaseCase):
    """R-07：报名状态对学生可见。"""

    def test_21_my_registrations_show_status(self):
        """TEST-V2-21：我的报名页显示状态标签（候补中 / 待审核 / 已取消）。"""
        aid = self.make_activity(capacity=1, requires_review=False)
        c1 = self.client()
        self.login(c1, "stu1")
        c1.post(f"/activities/{aid}/signup", follow_redirects=True)
        body = c1.get("/my/registrations").get_data(as_text=True)
        self.assertIn("已通过", body)

        c2 = self.client()
        self.login(c2, "stu2")
        c2.post(f"/activities/{aid}/signup", follow_redirects=True)
        body = c2.get("/my/registrations").get_data(as_text=True)
        self.assertIn("候补中", body)
        self.assertIn("第 1 位", body, "候补应显示位次")

    def test_22_detail_page_shows_own_status(self):
        """TEST-V2-22：活动详情页显示本人对该活动的当前状态。"""
        aid = self.make_activity(capacity=1, requires_review=True)
        c1 = self.client()
        self.login(c1, "stu1")
        c1.post(f"/activities/{aid}/signup", follow_redirects=True)
        body = c1.get(f"/activities/{aid}").get_data(as_text=True)
        self.assertIn("等待组织教师审核", body)

    def test_23_canceled_can_resign(self):
        """TEST-V2-23（D9）：取消后可以重新报名，复用同一条记录。"""
        aid = self.make_activity(capacity=2)
        c1 = self.client()
        self.login(c1, "stu1")
        c1.post(f"/activities/{aid}/signup", follow_redirects=True)
        c1.post(f"/activities/{aid}/cancel-signup", follow_redirects=True)
        self.assertEqual(self.reg_status(aid, "stu1"), REG_CANCELED)

        body = c1.post(f"/activities/{aid}/signup", follow_redirects=True).get_data(as_text=True)
        self.assertIn("报名成功", body)
        self.assertEqual(self.reg_status(aid, "stu1"), REG_APPROVED)

        with self.app.app_context():
            count = Registration.query.filter_by(activity_id=aid).count()
        self.assertEqual(count, 1, "重新报名应复用原记录，不新增")


# ==================================================================== R-09
class AdminCase(BaseCase):
    """R-09：管理员账号管理与平台活动监管，以及明确的边界。"""

    def test_24_admin_can_list_users(self):
        """TEST-V2-24：管理员可查看平台用户账号与状态。"""
        c = self.client()
        self.login(c, "admin")
        body = c.get("/admin/users").get_data(as_text=True)
        self.assertEqual(c.get("/admin/users").status_code, 200)
        self.assertIn("学生一", body)
        self.assertIn("活动组织教师", body)

    def test_25_disable_account_blocks_login(self):
        """TEST-V2-25：停用账号后该账号无法登录（D8）。"""
        with self.app.app_context():
            uid = User.query.filter_by(username="stu1").first().id
        c = self.client()
        self.login(c, "admin")
        c.post(f"/admin/users/{uid}/toggle", follow_redirects=True)

        victim = self.client()
        body = self.login(victim, "stu1").get_data(as_text=True)
        self.assertIn("已被停用", body, "停用账号应被拒绝登录并说明原因")
        self.assertEqual(victim.get("/my/registrations", follow_redirects=False).status_code, 302)

    def test_26_disable_does_not_touch_registrations(self):
        """TEST-V2-26（边界）：停用账号不改变其已有报名记录。"""
        aid = self.make_activity(capacity=2)
        c1 = self.client()
        self.login(c1, "stu1")
        c1.post(f"/activities/{aid}/signup", follow_redirects=True)
        self.assertEqual(self.reg_status(aid, "stu1"), REG_APPROVED)

        with self.app.app_context():
            uid = User.query.filter_by(username="stu1").first().id
        admin = self.client()
        self.login(admin, "admin")
        admin.post(f"/admin/users/{uid}/toggle", follow_redirects=True)

        self.assertEqual(self.reg_status(aid, "stu1"), REG_APPROVED, "报名记录不应被改动")

    def test_27_admin_cannot_disable_self(self):
        """TEST-V2-27（异常）：管理员不能停用当前登录的账号，避免把自己锁死。"""
        with self.app.app_context():
            uid = User.query.filter_by(username="admin").first().id
        c = self.client()
        self.login(c, "admin")
        body = c.post(f"/admin/users/{uid}/toggle", follow_redirects=True).get_data(as_text=True)
        self.assertIn("不能停用当前登录的管理员账号", body)

        with self.app.app_context():
            self.assertTrue(User.query.filter_by(username="admin").first().enabled)

    def test_28_admin_sees_all_activities(self):
        """TEST-V2-28：管理员可查看平台全部活动（含他人发布的）。"""
        self.make_activity(creator="teacher", capacity=2)
        self.make_activity(creator="teacher2", capacity=2)
        c = self.client()
        self.login(c, "admin")
        body = c.get("/admin/activities").get_data(as_text=True)
        self.assertIn("王老师", body)
        self.assertIn("李老师", body)

    def test_29_admin_can_take_down_activity(self):
        """TEST-V2-29：管理员可从平台层面下架违规活动（复用软下架 D12）。"""
        aid = self.make_activity(creator="teacher", capacity=2)
        c = self.client()
        self.login(c, "admin")
        body = c.post(f"/admin/activities/{aid}/cancel", follow_redirects=True).get_data(as_text=True)
        self.assertIn("已下架", body)

        with self.app.app_context():
            self.assertIsNotNone(db.session.get(Activity, aid).canceled_at)

    def test_30_admin_cannot_review_registration(self):
        """TEST-V2-30（权限边界）：管理员不介入报名业务，不能执行审核。"""
        aid = self.make_activity(capacity=2, requires_review=True)
        c1 = self.client()
        self.login(c1, "stu1")
        c1.post(f"/activities/{aid}/signup", follow_redirects=True)
        rid = self.reg_id(aid, "stu1")

        c = self.client()
        self.login(c, "admin")
        resp = c.post(f"/activities/{aid}/registrations/{rid}/review",
                      data={"decision": "approve"}, follow_redirects=False)
        self.assertEqual(resp.status_code, 403, "审核属教师职责，管理员无权执行")

    def test_31_non_admin_blocked(self):
        """TEST-V2-31（权限边界）：学生与教师访问管理员页面 → 403。"""
        for name in ("stu1", "teacher"):
            c = self.client()
            self.login(c, name)
            self.assertEqual(c.get("/admin/users", follow_redirects=False).status_code, 403)
            self.assertEqual(c.get("/admin/activities", follow_redirects=False).status_code, 403)


# =================================================================== 回归
class RegressionCase(BaseCase):
    """V1.0 核心流程回归：确认本轮改动没有破坏原有行为。"""

    def test_32_signup_blocked_after_deadline(self):
        """TEST-V2-32（回归）：报名截止后提交仍被拒绝（V1.0 约束 C2）。"""
        aid = self.make_activity(capacity=5, start_days=2, deadline_days=-1)
        c1 = self.client()
        self.login(c1, "stu1")
        body = c1.post(f"/activities/{aid}/signup", follow_redirects=True).get_data(as_text=True)
        self.assertIn("报名已截止", body)
        self.assertIsNone(self.reg_status(aid, "stu1"))

    def test_33_canceled_activity_rejects_signup(self):
        """TEST-V2-33（回归）：已下架活动不可报名。"""
        aid = self.make_activity(capacity=5)
        teacher = self.client()
        self.login(teacher, "teacher")
        teacher.post(f"/activities/{aid}/cancel", follow_redirects=True)

        c1 = self.client()
        self.login(c1, "stu1")
        body = c1.post(f"/activities/{aid}/signup", follow_redirects=True).get_data(as_text=True)
        self.assertIn("已下架", body)

    def test_34_teacher_cannot_edit_other_activity(self):
        """TEST-V2-34（回归）：教师不能编辑他人活动（V1.0 约束 C3）。"""
        aid = self.make_activity(creator="teacher", capacity=2)
        other = self.client()
        self.login(other, "teacher2")
        self.assertEqual(other.get(f"/activities/{aid}/edit", follow_redirects=False).status_code, 403)
        self.assertEqual(other.get(f"/activities/{aid}/signups", follow_redirects=False).status_code, 403)

    def test_35_teacher_cannot_signup(self):
        """TEST-V2-35（回归）：教师账号不参与报名。"""
        aid = self.make_activity(capacity=2)
        c = self.client()
        self.login(c, "teacher")
        self.assertEqual(c.post(f"/activities/{aid}/signup", follow_redirects=False).status_code, 403)

    def test_36_create_activity_with_review_and_eligibility(self):
        """TEST-V2-36（回归 + 新增）：活动表单可设置审核开关与资格说明。"""
        c = self.client()
        self.login(c, "teacher")
        c.post("/activities/new", data={
            "title": "需审核的讲座", "summary": "带资格要求", "location": "报告厅",
            "category_id": "", "start_time": (now() + timedelta(days=6)).strftime("%Y-%m-%dT%H:%M"),
            "end_time": (now() + timedelta(days=6, hours=2)).strftime("%Y-%m-%dT%H:%M"),
            "signup_deadline": (now() + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M"),
            "capacity": "30", "requires_review": "1", "eligibility_note": "限软件工程专业",
        }, follow_redirects=True)

        with self.app.app_context():
            activity = Activity.query.filter_by(title="需审核的讲座").first()
        self.assertIsNotNone(activity)
        self.assertTrue(activity.requires_review)
        self.assertEqual(activity.eligibility_note, "限软件工程专业")

    def test_37_activity_list_still_public(self):
        """TEST-V2-37（回归）：未登录访客仍可浏览活动列表与详情。"""
        aid = self.make_activity(capacity=2)
        guest = self.client()
        self.assertEqual(guest.get("/activities").status_code, 200)
        self.assertEqual(guest.get(f"/activities/{aid}").status_code, 200)

    def test_38_password_is_hashed(self):
        """TEST-V2-38（回归）：密码仍以哈希存储（V1.0 约束 C1）。"""
        with self.app.app_context():
            user = User.query.filter_by(username="stu1").first()
            self.assertNotIn(PASSWORD, user.password_hash)
            self.assertTrue(user.password_hash.startswith(("pbkdf2:", "scrypt:")))


if __name__ == "__main__":
    unittest.main(verbosity=2)

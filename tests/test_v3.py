"""V3.0 验证用例：数据驱动演化的 7 条需求（R-10 ~ R-16）。

对应用例编号 TEST-V3-xx，逐条覆盖 docs/07-V3.0需求演化.md 的验收标准。
沿用 V1/V2 的约定：只走 HTTP 路径、每个用例独立临时库。

另外保留一组「回归」用例，确认 V3.0 没有破坏 V1.0/V2.0 的核心规则。
"""

import unittest
from datetime import datetime, time, timedelta

from app.extensions import db
from app.models import (
    NOTIFY_ACTIVITY_CANCELED,
    NOTIFY_REVIEW_APPROVED,
    NOTIFY_WAITLIST_PROMOTED,
    REG_APPROVED,
    REG_PENDING,
    REG_WAITLIST,
    Activity,
    Notification,
    SignupAttempt,
    User,
    now,
)
from tests.test_v2 import PASSWORD, BaseCase


class V3Base(BaseCase):
    """在 V2 脚手架之上补几个 V3.0 需要的方法。"""

    def body(self, response) -> str:
        return response.get_data(as_text=True)

    def make_activity_at(self, start_time, deadline=None, capacity=10,
                         requires_review=False, creator="teacher", title="活动"):
        with self.app.app_context():
            owner = User.query.filter_by(username=creator).first()
            activity = Activity(
                title=title,
                summary="V3 用例活动",
                location="测试地点",
                start_time=start_time,
                end_time=start_time + timedelta(hours=2),
                signup_deadline=deadline or (start_time - timedelta(days=1)),
                capacity=capacity,
                creator_id=owner.id,
                requires_review=requires_review,
            )
            db.session.add(activity)
            db.session.commit()
            return activity.id

    def weekend_start(self):
        """与 activities/routes.py 的「本周末」口径保持一致。"""
        today = now().date()
        weekday = today.weekday()
        saturday = today - timedelta(days=1) if weekday == 6 else today + timedelta(days=5 - weekday)
        return datetime.combine(saturday, time(hour=10))

    def attempts(self, token=None):
        with self.app.app_context():
            query = SignupAttempt.query
            if token is not None:
                query = query.filter_by(token=token)
            return query.count()

    def notifications(self, username):
        with self.app.app_context():
            user = User.query.filter_by(username=username).first()
            return Notification.query.filter_by(user_id=user.id).order_by(Notification.id).all()

    def post_signup(self, client, activity_id, token=None):
        data = {}
        if token is not None:
            data["signup_token"] = token
        return client.post(f"/activities/{activity_id}/signup", data=data, follow_redirects=True)


# ==================================================================== R-10
class IdempotentSignupCase(V3Base):
    """R-10：重复提交返回同一结果，不再以「失败」呈现。"""

    def test_01_same_token_twice_returns_success(self):
        """TEST-V3-01：同一令牌提交两次 → 两次都是成功语义，只有一条记录。"""
        aid = self.make_activity(capacity=5)
        client = self.client()
        self.login(client, "stu1")
        token = "a" * 32

        first = self.post_signup(client, aid, token)
        second = self.post_signup(client, aid, token)

        self.assertIn("报名成功", self.body(first))
        self.assertIn("报名成功", self.body(second))
        self.assertEqual(self.reg_status(aid, "stu1"), REG_APPROVED)
        self.assertEqual(self.attempts(token), 1, "同一令牌只应留一条提交凭据")

    def test_02_different_token_shows_current_status(self):
        """TEST-V3-02：换一个令牌再报 → 展示当前状态，不出现否定词。"""
        aid = self.make_activity(capacity=5)
        client = self.client()
        self.login(client, "stu1")

        self.post_signup(client, aid, "b" * 32)
        body = self.body(self.post_signup(client, aid, "c" * 32))

        self.assertIn("提交过报名", body)
        self.assertIn("当前状态：已通过", body)
        self.assertNotIn("请勿重复报名", body)
        self.assertNotIn("报名失败", body)

    def test_03_no_duplicate_records_after_retry(self):
        """TEST-V3-03：连续提交 5 次 → 记录数仍为 1（数据库唯一约束 + 幂等）。"""
        aid = self.make_activity(capacity=5)
        client = self.client()
        self.login(client, "stu1")
        for index in range(5):
            self.post_signup(client, aid, f"{index:032x}")

        with self.app.app_context():
            from app.models import Registration

            count = Registration.query.filter_by(activity_id=aid).count()
        self.assertEqual(count, 1)

    def test_04_detail_page_carries_token(self):
        """TEST-V3-04：详情页的报名表单带一次性令牌（前端可验证的幂等前提）。"""
        aid = self.make_activity(capacity=5)
        client = self.client()
        self.login(client, "stu1")
        body = self.body(client.get(f"/activities/{aid}"))
        self.assertIn('name="signup_token"', body)

    def test_05_token_is_not_reused_across_activities(self):
        """TEST-V3-05（异常）：把 A 活动的令牌用到 B 活动 → 视为无效凭据，不误判。"""
        aid_a = self.make_activity(capacity=5)
        aid_b = self.make_activity(capacity=5)
        client = self.client()
        self.login(client, "stu1")
        token = "d" * 32
        self.post_signup(client, aid_a, token)

        body = self.body(self.post_signup(client, aid_b, token))
        self.assertIn("凭据无效", body)
        self.assertIsNone(self.reg_status(aid_b, "stu1"))


# ==================================================================== R-11 / R-13
class ResultPageCase(V3Base):
    """R-11 失败可解释 + R-13 结果落地页。"""

    def test_06_signup_redirects_to_result_page(self):
        """TEST-V3-06：提交后落到结果页，而不是一闪而过的提示。"""
        aid = self.make_activity(capacity=5)
        client = self.client()
        self.login(client, "stu1")

        response = client.post(f"/activities/{aid}/signup", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/registrations/result/", response.headers["Location"])

    def test_07_result_page_has_reason_and_next_step(self):
        """TEST-V3-07：结果页必须同时给出「为什么」与「现在能做什么」。"""
        aid = self.make_activity(capacity=5)
        client = self.client()
        self.login(client, "stu1")
        body = self.body(self.post_signup(client, aid))

        self.assertIn("为什么是这个结果", body)
        self.assertIn("现在可以做什么", body)
        self.assertIn("仍有空余名额", body)
        self.assertIn("查看我的报名", body)

    def test_08_refresh_result_page_does_not_resubmit(self):
        """TEST-V3-08：刷新结果页是纯 GET，不产生新的提交凭据。"""
        aid = self.make_activity(capacity=5)
        client = self.client()
        self.login(client, "stu1")
        response = client.post(f"/activities/{aid}/signup", follow_redirects=False)
        location = response.headers["Location"]

        client.get(location)
        client.get(location)
        client.get(location)

        self.assertEqual(self.attempts(), 1)

    def test_09_closed_signup_shows_actionable_reason(self):
        """TEST-V3-09（异常）：报名已截止 → 说明原因并给出下一步，而不是只报错。"""
        start = now() + timedelta(days=2)
        aid = self.make_activity_at(start, deadline=now() - timedelta(hours=1), capacity=5)
        client = self.client()
        self.login(client, "stu1")
        body = self.body(self.post_signup(client, aid))

        self.assertIn("报名已截止", body)
        self.assertIn("报名通道已于", body)
        self.assertIn("浏览其他仍在报名的活动", body)

    def test_10_result_page_is_private(self):
        """TEST-V3-10（安全）：用别人的结果链接 → 404，不泄漏报名信息。"""
        aid = self.make_activity(capacity=5)
        owner = self.client()
        self.login(owner, "stu1")
        response = owner.post(f"/activities/{aid}/signup", follow_redirects=False)
        location = response.headers["Location"]

        intruder = self.client()
        self.login(intruder, "stu2")
        self.assertEqual(intruder.get(location).status_code, 404)

    def test_11_unknown_token_404(self):
        """TEST-V3-11（异常）：不存在的凭据 → 404。"""
        client = self.client()
        self.login(client, "stu1")
        self.assertEqual(client.get("/registrations/result/" + "f" * 32).status_code, 404)


# ==================================================================== R-12
class FullCapacityCase(V3Base):
    """R-12：满员不是错误，而是候补。"""

    def test_12_full_activity_returns_waitlist_position(self):
        """TEST-V3-12：名额刚满时提交 → 成功语义 + 明确位次。"""
        aid = self.make_activity(capacity=1)
        c1 = self.client()
        self.login(c1, "stu1")
        self.post_signup(c1, aid)

        c2 = self.client()
        self.login(c2, "stu2")
        body = self.body(self.post_signup(c2, aid))

        self.assertIn("已进入候补队列", body)
        self.assertIn("第 1 位", body)
        self.assertIn("候补第 1 位", body)
        self.assertEqual(self.reg_status(aid, "stu2"), REG_WAITLIST)
        self.assertEqual(self.approved_count(aid), 1, "候补不得占用正式名额")

    def test_13_no_conflict_error_code_in_result(self):
        """TEST-V3-13：满员提交不出现「冲突 / 失败」这类结果码。"""
        aid = self.make_activity(capacity=1)
        c1 = self.client()
        self.login(c1, "stu1")
        self.post_signup(c1, aid)

        c2 = self.client()
        self.login(c2, "stu2")
        self.post_signup(c2, aid)
        with self.app.app_context():
            codes = [a.code for a in SignupAttempt.query.all()]
        self.assertNotIn("SIGNUP_FULL", codes)
        self.assertIn("SIGNUP_WAITLIST", codes)


# ==================================================================== R-14
class NotificationCase(V3Base):
    """R-14：状态变化主动触达。"""

    def test_14_review_approve_creates_notification(self):
        """TEST-V3-14：教师通过申请 → 学生收到通知，未读数可见。"""
        aid = self.make_activity(capacity=5, requires_review=True)
        student = self.client()
        self.login(student, "stu1")
        self.post_signup(student, aid)

        teacher = self.client()
        self.login(teacher, "teacher")
        reg_id = self.reg_id(aid, "stu1")
        teacher.post(f"/activities/{aid}/registrations/{reg_id}/review", data={"decision": "approve"})

        items = self.notifications("stu1")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].kind, NOTIFY_REVIEW_APPROVED)
        self.assertIn("报名已通过", items[0].title)

        body = self.body(student.get("/notifications"))
        self.assertIn("报名已通过", body)
        self.assertIn("1 条未读", body)

    def test_15_review_reject_creates_notification(self):
        """TEST-V3-15：教师拒绝申请 → 通知说明未通过，且不泄漏给他人。"""
        aid = self.make_activity(capacity=5, requires_review=True)
        student = self.client()
        self.login(student, "stu1")
        self.post_signup(student, aid)

        teacher = self.client()
        self.login(teacher, "teacher")
        teacher.post(
            f"/activities/{aid}/registrations/{self.reg_id(aid, 'stu1')}/review",
            data={"decision": "reject"},
        )

        self.assertEqual(self.notifications("stu1")[0].kind, "review_rejected")
        self.assertEqual(len(self.notifications("stu2")), 0)

    def test_16_promotion_creates_notification(self):
        """TEST-V3-16：候补被递补 → 收到「候补成功」，这是数据里最缺的一环。"""
        aid = self.make_activity(capacity=1)
        c1 = self.client()
        self.login(c1, "stu1")
        self.post_signup(c1, aid)

        c2 = self.client()
        self.login(c2, "stu2")
        self.post_signup(c2, aid)

        c1.post(f"/activities/{aid}/cancel-signup")
        items = self.notifications("stu2")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].kind, NOTIFY_WAITLIST_PROMOTED)
        self.assertIn("候补成功", items[0].title)
        self.assertEqual(self.reg_status(aid, "stu2"), REG_APPROVED)

    def test_17_cancel_activity_notifies_registrants(self):
        """TEST-V3-17：活动下架 → 已报名学生收到通知。"""
        aid = self.make_activity(capacity=5)
        student = self.client()
        self.login(student, "stu1")
        self.post_signup(student, aid)

        teacher = self.client()
        self.login(teacher, "teacher")
        teacher.post(f"/activities/{aid}/cancel")

        items = self.notifications("stu1")
        self.assertEqual(items[-1].kind, NOTIFY_ACTIVITY_CANCELED)
        self.assertIn("活动已下架", items[-1].title)

    def test_18_mark_read_reduces_unread(self):
        """TEST-V3-18：标记已读 → 未读数减少。"""
        aid = self.make_activity(capacity=5, requires_review=True)
        student = self.client()
        self.login(student, "stu1")
        self.post_signup(student, aid)
        teacher = self.client()
        self.login(teacher, "teacher")
        teacher.post(
            f"/activities/{aid}/registrations/{self.reg_id(aid, 'stu1')}/review",
            data={"decision": "approve"},
        )

        item = self.notifications("stu1")[0]
        student.post(f"/notifications/{item.id}/read")
        body = self.body(student.get("/notifications"))
        self.assertNotIn("条未读", body)
        self.assertEqual(len(self.notifications("stu1")), 1, "已读不等于删除")

    def test_19_cannot_read_others_notification(self):
        """TEST-V3-19（安全）：不能把别人的通知标记为已读。"""
        aid = self.make_activity(capacity=5, requires_review=True)
        student = self.client()
        self.login(student, "stu1")
        self.post_signup(student, aid)
        teacher = self.client()
        self.login(teacher, "teacher")
        teacher.post(
            f"/activities/{aid}/registrations/{self.reg_id(aid, 'stu1')}/review",
            data={"decision": "approve"},
        )
        item = self.notifications("stu1")[0]

        other = self.client()
        self.login(other, "stu2")
        self.assertEqual(other.post(f"/notifications/{item.id}/read").status_code, 404)

    def test_20_mark_all_read(self):
        """TEST-V3-20：一键已读 → 全部通知 read_at 非空。"""
        aid = self.make_activity(capacity=5, requires_review=True)
        student = self.client()
        self.login(student, "stu1")
        self.post_signup(student, aid)
        teacher = self.client()
        self.login(teacher, "teacher")
        teacher.post(
            f"/activities/{aid}/registrations/{self.reg_id(aid, 'stu1')}/review",
            data={"decision": "approve"},
        )
        student.post("/notifications/read-all")

        with self.app.app_context():
            unread = Notification.query.filter_by(read_at=None).count()
        self.assertEqual(unread, 0)


# ==================================================================== R-15
class MyRegistrationCase(V3Base):
    """R-15：我的报名状态透明。"""

    def test_21_waitlist_position_and_updated_time(self):
        """TEST-V3-21：候补记录显示位次、前方人数与状态更新时间。"""
        aid = self.make_activity(capacity=1)
        c1 = self.client()
        self.login(c1, "stu1")
        self.post_signup(c1, aid)

        c2 = self.client()
        self.login(c2, "stu2")
        self.post_signup(c2, aid)

        body = self.body(c2.get("/my/registrations"))
        self.assertIn("第 1 位，前面还有 0 人", body)
        self.assertIn("更新于", body)

    def test_22_status_has_human_explanation(self):
        """TEST-V3-22：状态旁有人话解释，而不是只有一个标签。"""
        aid = self.make_activity(capacity=1)
        c1 = self.client()
        self.login(c1, "stu1")
        self.post_signup(c1, aid)
        c2 = self.client()
        self.login(c2, "stu2")
        self.post_signup(c2, aid)

        body = self.body(c2.get("/my/registrations"))
        self.assertIn("等待空位自动补位", body)
        self.assertIn("不需要反复刷新", body)


# ==================================================================== R-16
class ListFilterCase(V3Base):
    """R-16：快捷筛选与卡片信息密度。"""

    def setUp(self):
        super().setUp()
        self.weekend_id = self.make_activity_at(
            self.weekend_start(), deadline=now() + timedelta(days=30), title="周末活动"
        )
        self.soon_id = self.make_activity_at(
            now() + timedelta(days=2), deadline=now() + timedelta(days=1), title="三天后活动"
        )
        self.later_id = self.make_activity_at(
            now() + timedelta(days=20), deadline=now() + timedelta(days=19), title="三周后活动"
        )
        self.review_id = self.make_activity_at(
            now() + timedelta(days=3),
            deadline=now() + timedelta(days=2),
            requires_review=True,
            title="需审核活动",
        )
        self.full_id = self.make_activity_at(
            now() + timedelta(days=4), deadline=now() + timedelta(days=3),
            capacity=1, title="已满活动",
        )
        filler = self.client()
        self.login(filler, "stu3")
        self.post_signup(filler, self.full_id)

    def test_23_weekend_filter(self):
        """TEST-V3-23：本周末筛选只保留周末开始的活动。"""
        body = self.body(self.client().get("/activities?when=weekend"))
        self.assertIn("周末活动", body)
        self.assertNotIn("三周后活动", body)

    def test_24_week_filter(self):
        """TEST-V3-24：未来 7 天筛选排除三周后的活动。"""
        body = self.body(self.client().get("/activities?when=week"))
        self.assertIn("三天后活动", body)
        self.assertNotIn("三周后活动", body)

    def test_25_vacancy_filter(self):
        """TEST-V3-25：仅看还有名额 → 排除已满活动。"""
        body = self.body(self.client().get("/activities?vacancy=1"))
        self.assertNotIn("已满活动", body)
        self.assertIn("三天后活动", body)

    def test_26_no_review_filter(self):
        """TEST-V3-26：仅看无需审核 → 排除需审核活动。"""
        body = self.body(self.client().get("/activities?review=0"))
        self.assertNotIn("需审核活动", body)
        self.assertIn("三天后活动", body)

    def test_27_combined_filters(self):
        """TEST-V3-27：筛选条件可组合（未来 7 天 + 无需审核）。"""
        body = self.body(self.client().get("/activities?when=week&review=0"))
        self.assertIn("三天后活动", body)
        self.assertNotIn("需审核活动", body)
        self.assertNotIn("三周后活动", body)

    def test_28_filter_links_keep_other_conditions(self):
        """TEST-V3-28：快捷筛选 chip 的链接保留其余条件，不会把用户已选的筛掉。"""
        body = self.body(self.client().get("/activities?when=week&review=0"))
        self.assertIn("when=week", body)
        self.assertIn("review=0", body)

    def test_29_card_shows_remaining_and_flags(self):
        """TEST-V3-29：卡片直接给出剩余名额、需审核标记，不必点进详情。"""
        body = self.body(self.client().get("/activities"))
        self.assertIn("剩 0", body)          # 已满活动的剩余名额
        self.assertIn("需审核", body)
        self.assertIn("报名", body)

    def test_30_card_shows_my_registration(self):
        """TEST-V3-30：已报名的活动在列表里就能看出状态。"""
        client = self.client()
        self.login(client, "stu2")
        self.post_signup(client, self.soon_id)
        body = self.body(client.get("/activities"))
        self.assertIn("我已报名", body)
        self.assertIn("已通过", body)


# ==================================================================== 回归
class RegressionCase(V3Base):
    """V3.0 不能破坏 V1/V2 已确认的规则。"""

    def test_31_approval_flow_still_works(self):
        """TEST-V3-31（回归）：需审核活动 → 待审核 → 教师通过 → 已通过。"""
        aid = self.make_activity(capacity=5, requires_review=True)
        student = self.client()
        self.login(student, "stu1")
        self.post_signup(student, aid)
        self.assertEqual(self.reg_status(aid, "stu1"), REG_PENDING)

        teacher = self.client()
        self.login(teacher, "teacher")
        teacher.post(
            f"/activities/{aid}/registrations/{self.reg_id(aid, 'stu1')}/review",
            data={"decision": "approve"},
        )
        self.assertEqual(self.reg_status(aid, "stu1"), REG_APPROVED)

    def test_32_cancel_still_promotes(self):
        """TEST-V3-32（回归）：取消报名 → 候补第一位自动补上。"""
        aid = self.make_activity(capacity=1)
        c1 = self.client()
        self.login(c1, "stu1")
        self.post_signup(c1, aid)
        c2 = self.client()
        self.login(c2, "stu2")
        self.post_signup(c2, aid)

        c1.post(f"/activities/{aid}/cancel-signup")
        self.assertEqual(self.reg_status(aid, "stu2"), REG_APPROVED)
        self.assertEqual(self.approved_count(aid), 1)

    def test_33_teacher_cannot_signup(self):
        """TEST-V3-33（回归）：教师账号不能报名。"""
        aid = self.make_activity(capacity=5)
        teacher = self.client()
        self.login(teacher, "teacher")
        teacher.post(f"/activities/{aid}/signup")
        self.assertIsNone(self.reg_status(aid, "teacher"))

    def test_34_deadline_enforced_server_side(self):
        """TEST-V3-34（回归）：绕过页面直接提交也必须被截止规则拦住。"""
        aid = self.make_activity_at(
            now() + timedelta(days=2), deadline=now() - timedelta(minutes=1)
        )
        client = self.client()
        self.login(client, "stu1")
        body = self.body(self.post_signup(client, aid))
        self.assertIn("报名已截止", body)
        self.assertIsNone(self.reg_status(aid, "stu1"))


if __name__ == "__main__":
    unittest.main()

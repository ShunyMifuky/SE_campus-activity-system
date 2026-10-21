"""业务规则验证用例（对应 TEST-01 ~ TEST-06）。

设计说明：
  - 每条用例使用独立的临时 SQLite 数据库，用例之间互不影响
  - 只通过 HTTP 接口（test_client）访问系统，不直接调用 service，
    验证的是"用户真实能走通的路径"，而不是内部函数的正确性
  - 覆盖正常流程与异常分支：重复报名、名额已满、报名已截止、越权访问
  - V2.0 规则演进后，本文件有 4 条断言按新行为更新（满员改为进入候补、
    取消保留记录、名额只统计已通过），每处均在其用例内注明原因

实现注意（踩过的坑）：
  不能在请求之间长期持有一个应用上下文。Flask-Login 把当前登录用户缓存在
  应用上下文对象 `g` 上；如果外层一直持有应用上下文，多个 test_client 之间
  会共用同一个 `g`，导致 current_user 串号、登录接口被"已登录"分支直接短路。
  因此这里只在访问数据库时临时开启应用上下文。

运行方式（在项目根目录执行）：
    python -m unittest discover -s tests -v
"""

import os
import tempfile
import unittest
from datetime import timedelta

from app import create_app
from app.extensions import db
from app.models import (
    REG_APPROVED,
    ROLE_STUDENT,
    ROLE_TEACHER,
    STATUS_CLOSED,
    Activity,
    Category,
    Registration,
    User,
    now,
)

DEMO_PASSWORD = "Demo@2026"


def make_app(db_path: str):
    """构造一个使用临时数据库的应用实例。"""

    class TestConfig:
        SECRET_KEY = "v1-verification-secret"
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + db_path
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        PERMANENT_SESSION_LIFETIME = 3600

    return create_app(TestConfig)


class BaseCase(unittest.TestCase):
    """公共脚手架：每个用例一个全新的空库，数据库访问走短生命周期上下文。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.app = make_app(os.path.join(self._tmp.name, "verify.db"))
        with self.app.app_context():
            self._seed()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self._tmp.cleanup()

    # ------------------------------------------------------------ 数据准备
    def _seed(self):
        category = Category(name="讲座报告", sort_order=1)
        db.session.add(category)
        db.session.flush()
        self.category_id = category.id

        for username, real_name, role, student_no in [
            ("teacher_a", "王泰然", ROLE_TEACHER, "T2026001"),
            ("teacher_b", "唐佳涵", ROLE_TEACHER, "T2026002"),
            ("student_1", "林翔宇", ROLE_STUDENT, "2023001"),
            ("student_2", "陈嘉禾", ROLE_STUDENT, "2023002"),
            ("student_3", "赵一鸣", ROLE_STUDENT, "2023003"),
        ]:
            user = User(username=username, real_name=real_name, student_no=student_no, role=role)
            user.set_password(DEMO_PASSWORD)
            db.session.add(user)

        db.session.commit()
        self.user_ids = {u.username: u.id for u in User.query.all()}

    def uid(self, username: str) -> int:
        return self.user_ids[username]

    # ------------------------------------------------------ 数据库访问助手
    def make_activity(
        self,
        *,
        creator="teacher_a",
        title="验证用活动",
        start_in_days=5,
        deadline_in_days=4,
        capacity=10,
    ) -> int:
        """创建活动，返回活动 id。"""
        base = now().replace(second=0, microsecond=0)
        with self.app.app_context():
            activity = Activity(
                title=title,
                summary="验证用活动简介",
                location="实验楼 A101",
                start_time=base + timedelta(days=start_in_days),
                end_time=base + timedelta(days=start_in_days, hours=2),
                signup_deadline=base + timedelta(days=deadline_in_days),
                capacity=capacity,
                category_id=self.category_id,
                creator_id=self.uid(creator),
            )
            db.session.add(activity)
            db.session.commit()
            return activity.id

    def add_registration(self, activity_id: int, username: str) -> None:
        with self.app.app_context():
            db.session.add(
                Registration(activity_id=activity_id, user_id=self.uid(username))
            )
            db.session.commit()

    def activity_status(self, activity_id: int) -> str:
        with self.app.app_context():
            return db.session.get(Activity, activity_id).status

    def registered_count(self, activity_id: int) -> int:
        """报名记录总数（含候补、待审核与已取消）。"""
        with self.app.app_context():
            return Registration.query.filter_by(activity_id=activity_id).count()

    def approved_count(self, activity_id: int) -> int:
        """正式参加人数。

        V2.0 起名额只统计「已通过」，候补与待审核均不占用名额，
        因此不能用记录总数代表名额占用情况。
        """
        with self.app.app_context():
            return Registration.query.filter_by(
                activity_id=activity_id, status=REG_APPROVED
            ).count()

    def registration_total(self) -> int:
        with self.app.app_context():
            return Registration.query.count()

    def activity_titles(self) -> list:
        with self.app.app_context():
            return [a.title for a in Activity.query.all()]

    def password_hash_of(self, username: str) -> str:
        with self.app.app_context():
            return User.query.filter_by(username=username).first().password_hash

    # ------------------------------------------------------------ HTTP 助手
    def client(self):
        return self.app.test_client()

    def login(self, client, username, password=DEMO_PASSWORD):
        return client.post(
            "/auth/login",
            data={"username": username, "password": password},
            follow_redirects=True,
        )

    def body(self, response) -> str:
        return response.get_data(as_text=True)


# ============================================================ TEST-01
class Test01UserAccount(BaseCase):
    """TEST-01 用户注册与登录（REQ-01）。"""

    def test_01a_注册后可正常登录(self):
        client = self.client()
        response = client.post(
            "/auth/register",
            data={
                "username": "new_student",
                "real_name": "孙晓",
                "student_no": "2023004",
                "role": ROLE_STUDENT,
                "password": "Passw0rd",
                "confirm_password": "Passw0rd",
            },
            follow_redirects=True,
        )
        self.assertIn("注册成功", self.body(response))
        self.assertIn("欢迎回来", self.body(self.login(client, "new_student", "Passw0rd")))

    def test_01b_密码错误被拒绝(self):
        client = self.client()
        response = self.login(client, "student_1", "wrong-password")
        self.assertIn("账号或密码不正确", self.body(response))

    def test_01c_数据库不保存明文密码(self):
        password_hash = self.password_hash_of("student_1")
        self.assertNotEqual(password_hash, DEMO_PASSWORD)
        self.assertNotIn(DEMO_PASSWORD, password_hash)

    def test_01d_重复账号无法注册(self):
        client = self.client()
        response = client.post(
            "/auth/register",
            data={
                "username": "student_1",
                "real_name": "重名",
                "role": ROLE_STUDENT,
                "password": "Passw0rd",
                "confirm_password": "Passw0rd",
            },
            follow_redirects=True,
        )
        self.assertIn("已被注册", self.body(response))


# ============================================================ TEST-02
class Test02RolePermission(BaseCase):
    """TEST-02 角色与资源归属权限（REQ-02）。"""

    def test_02a_学生不能进入活动发布页(self):
        client = self.client()
        self.login(client, "student_1")
        self.assertEqual(client.get("/activities/new").status_code, 403)

    def test_02b_教师可以进入活动发布页(self):
        client = self.client()
        self.login(client, "teacher_a")
        self.assertEqual(client.get("/activities/new").status_code, 200)

    def test_02c_教师不能编辑他人发布的活动(self):
        activity_id = self.make_activity(creator="teacher_a")
        client = self.client()
        self.login(client, "teacher_b")
        self.assertEqual(client.get(f"/activities/{activity_id}/edit").status_code, 403)

    def test_02d_教师不能查看他人活动的报名名单(self):
        activity_id = self.make_activity(creator="teacher_a")
        client = self.client()
        self.login(client, "teacher_b")
        self.assertEqual(client.get(f"/activities/{activity_id}/signups").status_code, 403)

    def test_02e_教师不能下架他人发布的活动(self):
        activity_id = self.make_activity(creator="teacher_a")
        client = self.client()
        self.login(client, "teacher_b")
        client.post(f"/activities/{activity_id}/cancel", follow_redirects=True)

        with self.app.app_context():
            activity = db.session.get(Activity, activity_id)
            self.assertIsNone(activity.canceled_at, "他人活动不应被下架")


# ============================================================ TEST-03
class Test03ActivityManagement(BaseCase):
    """TEST-03 活动发布、修改与下架（REQ-03）。"""

    def test_03a_教师发布活动后学生可见(self):
        client = self.client()
        self.login(client, "teacher_a")
        response = client.post(
            "/activities/new",
            data={
                "title": "人工智能前沿技术讲座",
                "summary": "面向全校学生",
                "location": "图书馆报告厅",
                "category_id": str(self.category_id),
                "start_time": "2026-12-01T14:00",
                "end_time": "2026-12-01T16:00",
                "signup_deadline": "2026-11-30T18:00",
                "capacity": "80",
            },
            follow_redirects=True,
        )
        self.assertIn("已发布", self.body(response))

        visitor = self.client()
        self.assertIn("人工智能前沿技术讲座", self.body(visitor.get("/activities")))

    def test_03b_结束时间早于开始时间被拒绝(self):
        client = self.client()
        self.login(client, "teacher_a")
        response = client.post(
            "/activities/new",
            data={
                "title": "时间错误的活动",
                "summary": "",
                "location": "A101",
                "category_id": str(self.category_id),
                "start_time": "2026-12-01T16:00",
                "end_time": "2026-12-01T14:00",
                "signup_deadline": "2026-11-30T18:00",
                "capacity": "10",
            },
            follow_redirects=True,
        )
        self.assertIn("活动结束时间必须晚于开始时间", self.body(response))
        self.assertNotIn("时间错误的活动", self.activity_titles())

    def test_03c_报名截止晚于开始时间被拒绝(self):
        client = self.client()
        self.login(client, "teacher_a")
        response = client.post(
            "/activities/new",
            data={
                "title": "截止时间错乱的活动",
                "summary": "",
                "location": "A101",
                "category_id": str(self.category_id),
                "start_time": "2026-12-01T14:00",
                "end_time": "2026-12-01T16:00",
                "signup_deadline": "2026-12-01T15:00",
                "capacity": "10",
            },
            follow_redirects=True,
        )
        self.assertIn("报名截止时间不能晚于活动开始时间", self.body(response))

    def test_03d_人数上限不能低于正式参加人数(self):
        activity_id = self.make_activity(capacity=10)
        self.add_registration(activity_id, "student_1")
        self.add_registration(activity_id, "student_2")

        client = self.client()
        self.login(client, "teacher_a")
        base = now().replace(second=0, microsecond=0)
        response = client.post(
            f"/activities/{activity_id}/edit",
            data={
                "title": "验证用活动",
                "summary": "验证用活动简介",
                "location": "实验楼 A101",
                "category_id": str(self.category_id),
                "start_time": (base + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M"),
                "end_time": (base + timedelta(days=5, hours=2)).strftime("%Y-%m-%dT%H:%M"),
                "signup_deadline": (base + timedelta(days=4)).strftime("%Y-%m-%dT%H:%M"),
                "capacity": "1",
            },
            follow_redirects=True,
        )
        # V2.0：名额口径改为只统计「正式参加」，候补与待审核不计入
        self.assertIn("人数上限不能小于当前正式参加人数", self.body(response))

    def test_03e_下架后列表不可见且不可报名(self):
        activity_id = self.make_activity()
        client = self.client()
        self.login(client, "teacher_a")
        self.assertIn("已下架", self.body(client.post(f"/activities/{activity_id}/cancel", follow_redirects=True)))

        visitor = self.client()
        self.assertNotIn("验证用活动", self.body(visitor.get("/activities")))

        student = self.client()
        self.login(student, "student_1")
        student.post(f"/activities/{activity_id}/signup", follow_redirects=True)
        self.assertEqual(self.registration_total(), 0)


# ============================================================ TEST-04
class Test04BrowseAndFilter(BaseCase):
    """TEST-04 活动浏览与筛选（REQ-04）。"""

    def test_04a_未登录可浏览列表与详情(self):
        activity_id = self.make_activity(title="公开可浏览的活动")
        client = self.client()
        self.assertEqual(client.get("/activities").status_code, 200)
        response = client.get(f"/activities/{activity_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("公开可浏览的活动", self.body(response))

    def test_04b_按关键词筛选(self):
        self.make_activity(title="校园羽毛球混合双打赛")
        self.make_activity(title="人工智能前沿技术讲座")
        listing = self.body(self.client().get("/activities?q=羽毛球"))
        self.assertIn("校园羽毛球混合双打赛", listing)
        self.assertNotIn("人工智能前沿技术讲座", listing)

    def test_04c_按分类筛选(self):
        with self.app.app_context():
            other = Category(name="文体活动", sort_order=2)
            db.session.add(other)
            db.session.commit()
            other_id = other.id

        base = now().replace(second=0, microsecond=0)
        with self.app.app_context():
            db.session.add(
                Activity(
                    title="文体分类活动",
                    summary="",
                    location="体育馆",
                    start_time=base + timedelta(days=3),
                    end_time=base + timedelta(days=3, hours=2),
                    signup_deadline=base + timedelta(days=2),
                    capacity=10,
                    category_id=other_id,
                    creator_id=self.uid("teacher_a"),
                )
            )
            db.session.commit()
        self.make_activity(title="讲座分类活动")

        listing = self.body(self.client().get(f"/activities?category={other_id}"))
        self.assertIn("文体分类活动", listing)
        self.assertNotIn("讲座分类活动", listing)

    def test_04d_按状态筛选(self):
        self.make_activity(title="正在进行报名的活动", start_in_days=5, deadline_in_days=4)
        self.make_activity(title="报名已截止的活动", start_in_days=5, deadline_in_days=-1)

        client = self.client()
        open_listing = self.body(client.get("/activities?status=open"))
        self.assertIn("正在进行报名的活动", open_listing)
        self.assertNotIn("报名已截止的活动", open_listing)

        closed_listing = self.body(client.get("/activities?status=closed"))
        self.assertIn("报名已截止的活动", closed_listing)
        self.assertNotIn("正在进行报名的活动", closed_listing)

    def test_04e_不存在的活动返回404(self):
        self.assertEqual(self.client().get("/activities/999999").status_code, 404)


# ============================================================ TEST-05
class Test05Signup(BaseCase):
    """TEST-05 活动报名与取消报名（REQ-05）。"""

    def test_05a_学生在报名截止前报名成功(self):
        activity_id = self.make_activity(capacity=10)
        client = self.client()
        self.login(client, "student_1")

        self.assertIn(
            "报名成功",
            self.body(client.post(f"/activities/{activity_id}/signup", follow_redirects=True)),
        )
        self.assertEqual(self.registered_count(activity_id), 1)
        self.assertIn("验证用活动", self.body(client.get("/my/registrations")))

    def test_05b_重复报名返回当前状态(self):
        """V3.0 R-10：重复报名不再报错，返回「已提交过 + 当前状态」，且不新增记录。"""
        activity_id = self.make_activity(capacity=10)
        client = self.client()
        self.login(client, "student_1")
        client.post(f"/activities/{activity_id}/signup", follow_redirects=True)

        response = client.post(f"/activities/{activity_id}/signup", follow_redirects=True)
        body = self.body(response)
        self.assertIn("提交过报名", body)
        self.assertIn("当前状态：已通过", body)
        self.assertNotIn("请勿重复报名", body)
        self.assertEqual(self.registered_count(activity_id), 1)

    def test_05c_名额已满时进入候补队列(self):
        """规则演进：V1.0 满员即拒；V2.0 保留报名入口并转入候补（R-01）。"""
        activity_id = self.make_activity(capacity=1)

        first = self.client()
        self.login(first, "student_1")
        self.assertIn(
            "报名成功",
            self.body(first.post(f"/activities/{activity_id}/signup", follow_redirects=True)),
        )

        second = self.client()
        self.login(second, "student_2")
        response = second.post(f"/activities/{activity_id}/signup", follow_redirects=True)
        self.assertIn("已进入候补队列", self.body(response))
        # 正式名额仍只有 1 个：第二人进入候补，不占用名额
        self.assertEqual(self.approved_count(activity_id), 1)
        self.assertEqual(self.registered_count(activity_id), 2)

    def test_05d_报名截止后不能再报名(self):
        """关键异常分支：截止时间已过，即使名额未满也不允许报名。"""
        activity_id = self.make_activity(start_in_days=5, deadline_in_days=-1, capacity=10)
        self.assertEqual(self.activity_status(activity_id), STATUS_CLOSED)

        client = self.client()
        self.login(client, "student_1")
        response = client.post(f"/activities/{activity_id}/signup", follow_redirects=True)

        self.assertIn("报名已截止", self.body(response))
        self.assertEqual(self.registered_count(activity_id), 0)

    def test_05e_教师账号不能报名(self):
        activity_id = self.make_activity()
        client = self.client()
        self.login(client, "teacher_b")
        self.assertEqual(client.post(f"/activities/{activity_id}/signup").status_code, 403)

    def test_05f_取消报名后可再次报名(self):
        activity_id = self.make_activity(capacity=1)
        client = self.client()
        self.login(client, "student_1")
        client.post(f"/activities/{activity_id}/signup", follow_redirects=True)

        self.assertIn(
            "已取消报名",
            self.body(client.post(f"/activities/{activity_id}/cancel-signup", follow_redirects=True)),
        )
        # V2.0：取消不再物理删除记录，而是置为「已取消」供教师追溯，
        # 因此正式参加人数归零，但报名记录仍保留 1 条
        self.assertEqual(self.approved_count(activity_id), 0)
        self.assertEqual(self.registered_count(activity_id), 1)

        self.assertIn(
            "报名成功",
            self.body(client.post(f"/activities/{activity_id}/signup", follow_redirects=True)),
        )
        # 复用原记录改状态，不新增记录
        self.assertEqual(self.approved_count(activity_id), 1)
        self.assertEqual(self.registered_count(activity_id), 1)


# ============================================================ TEST-06
class Test06Roster(BaseCase):
    """TEST-06 报名名单与名额统计（REQ-06）。"""

    def test_06a_名单与报名记录一致(self):
        activity_id = self.make_activity(capacity=10)
        for username in ["student_1", "student_2", "student_3"]:
            client = self.client()
            self.login(client, username)
            client.post(f"/activities/{activity_id}/signup", follow_redirects=True)

        teacher = self.client()
        self.login(teacher, "teacher_a")
        response = teacher.get(f"/activities/{activity_id}/signups")
        self.assertEqual(response.status_code, 200)

        page = self.body(response)
        # 用学号做断言，避免与页头当前登录用户姓名混淆
        for student_no in ["2023001", "2023002", "2023003"]:
            self.assertIn(student_no, page)
        self.assertEqual(self.registered_count(activity_id), 3)

    def test_06b_剩余名额计算正确(self):
        activity_id = self.make_activity(capacity=3)
        for username in ["student_1", "student_2"]:
            client = self.client()
            self.login(client, username)
            client.post(f"/activities/{activity_id}/signup", follow_redirects=True)

        self.assertEqual(self.registered_count(activity_id), 2)

        teacher = self.client()
        self.login(teacher, "teacher_a")
        page = self.body(teacher.get(f"/activities/{activity_id}/signups"))
        self.assertIn("剩余 1 个名额", page)

    def test_06c_取消报名后名单同步更新(self):
        activity_id = self.make_activity(capacity=3)
        client = self.client()
        self.login(client, "student_1")
        client.post(f"/activities/{activity_id}/signup", follow_redirects=True)
        client.post(f"/activities/{activity_id}/cancel-signup", follow_redirects=True)

        teacher = self.client()
        self.login(teacher, "teacher_a")
        page = self.body(teacher.get(f"/activities/{activity_id}/signups"))
        # V2.0：名单按状态分块展示。取消后正式参加名单清空，
        # 但记录转入「已取消」分块保留，便于教师追溯名额流动
        self.assertIn("暂时还没有正式参加的学生", page)
        self.assertIn("已取消", page)

    def test_06d_不限人数活动显示不限(self):
        activity_id = self.make_activity(capacity=0)
        teacher = self.client()
        self.login(teacher, "teacher_a")
        self.assertIn("不限", self.body(teacher.get(f"/activities/{activity_id}/signups")))


# ====================================================== 完成依据 E3
class PersistenceTest(unittest.TestCase):
    """完成依据 E3：服务重启后数据仍然存在。"""

    def test_数据在服务重启后仍然保留(self):
        tmp = tempfile.TemporaryDirectory()
        db_path = os.path.join(tmp.name, "persist.db")

        first_app = make_app(db_path)
        with first_app.app_context():
            category = Category(name="讲座报告", sort_order=1)
            db.session.add(category)
            db.session.commit()
            category_id = category.id
            db.session.remove()
            db.engine.dispose()

        # 模拟重启：重新创建应用实例，连接同一个数据库文件
        second_app = make_app(db_path)
        with second_app.app_context():
            self.assertIsNotNone(db.session.get(Category, category_id))
            db.session.remove()
            db.engine.dispose()

        tmp.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=2)

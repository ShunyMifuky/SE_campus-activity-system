"""初始化基础数据：活动分类、演示账号与示例活动。

用法：
    python -m app.seed            # 幂等写入，已存在的数据不会重复创建
    python -m app.seed --reset    # 先清空所有数据再重新初始化

V2.0 补充（实验二）：
    新增系统管理员账号，并追加「需审核」与「已满员带候补」两类演示活动，
    便于直接演示教师审核与候补递补，无需手工造数据。

安全说明（约束 C6）：下面出现的口令只是本地演示账号的口令，
入库前统一经 Werkzeug 哈希处理，数据库中不保存明文，也不随版本库分发真实凭据。
"""

import sys
from datetime import timedelta

from . import create_app
from .extensions import db
from .models import (
    REG_APPROVED,
    REG_WAITLIST,
    ROLE_ADMIN,
    ROLE_STUDENT,
    ROLE_TEACHER,
    Activity,
    Category,
    Registration,
    User,
    now,
)

DEMO_PASSWORD = "Demo@2026"

CATEGORY_SEED = [
    ("讲座报告", 1),
    ("文体活动", 2),
    ("志愿服务", 3),
    ("社团活动", 4),
    ("科技竞赛", 5),
]

USER_SEED = [
    ("wangtairan", "王泰然", "T2026001", ROLE_TEACHER),
    ("tangjiahan", "唐佳涵", "T2026002", ROLE_TEACHER),
    ("linxiangyu", "林翔宇", "2023001", ROLE_STUDENT),
    ("chenjiahe", "陈嘉禾", "2023002", ROLE_STUDENT),
    ("zhaoyiming", "赵一鸣", "2023003", ROLE_STUDENT),
    ("sunxiao", "孙晓", "2023004", ROLE_STUDENT),
    # V2.0（R-09）：平台账号与活动秩序的管理者，不参与具体活动的报名
    ("admin", "系统管理员", "A2026001", ROLE_ADMIN),
]


def seed_categories() -> int:
    created = 0
    for name, order in CATEGORY_SEED:
        if Category.query.filter_by(name=name).first() is None:
            db.session.add(Category(name=name, sort_order=order))
            created += 1
    db.session.commit()
    return created


def seed_users() -> int:
    created = 0
    for username, real_name, student_no, role in USER_SEED:
        if User.query.filter_by(username=username).first() is None:
            user = User(username=username, real_name=real_name, student_no=student_no, role=role)
            user.set_password(DEMO_PASSWORD)
            db.session.add(user)
            created += 1
    db.session.commit()
    return created


def seed_activities() -> int:
    """写入 5 个示例活动：覆盖列表筛选、需审核、已满员带候补三类场景。"""
    teacher = User.query.filter_by(username="wangtairan").first()
    if teacher is None or Activity.query.count() > 0:
        return 0

    base = now().replace(second=0, microsecond=0)
    category_ids = {c.name: c.id for c in Category.query.all()}

    plans = [
        {
            "title": "人工智能前沿技术讲座",
            "summary": "邀请计算机学院老师介绍大模型与智能体的最新进展，面向全校学生开放，"
                       "无需具备编程基础。讲座结束后设有提问环节。",
            "location": "图书馆报告厅",
            "category_id": category_ids.get("讲座报告"),
            "start_time": base + timedelta(days=5, hours=2),
            "end_time": base + timedelta(days=5, hours=4),
            "signup_deadline": base + timedelta(days=4, hours=20),
            "capacity": 120,
        },
        {
            "title": "校园羽毛球混合双打赛",
            "summary": "以学院为单位报名，混合双打赛制，先小组赛后淘汰赛。"
                       "报名时请自行组队，未组队者由组委会随机配对。",
            "location": "体育馆二层羽毛球区",
            "category_id": category_ids.get("文体活动"),
            "start_time": base + timedelta(days=10, hours=1),
            "end_time": base + timedelta(days=10, hours=6),
            "signup_deadline": base + timedelta(days=8, hours=20),
            "capacity": 32,
        },
        {
            "title": "图书馆书架整理志愿服务",
            "summary": "协助图书馆完成社科类图书的上架与排序工作，计志愿服务时长 4 小时。"
                       "名额不限，欢迎随时参加。",
            "location": "图书馆三层社科阅览区",
            "category_id": category_ids.get("志愿服务"),
            "start_time": base - timedelta(days=3),
            "end_time": base - timedelta(days=3) + timedelta(hours=4),
            "signup_deadline": base - timedelta(days=4),
            "capacity": 0,
        },
        {
            # 演示 R-04/R-05/R-06：需审核 → 教师逐个确认 → 先资格后名额
            "title": "实验室开放日（需审核）",
            "summary": "开放电子实验室供学生动手实践，需具备基础电路知识。"
                       "报名后由组织教师逐个确认资格，通过后按当时名额安排。",
            "location": "实验楼 B204 电子实验室",
            "category_id": category_ids.get("科技竞赛"),
            "start_time": base + timedelta(days=7, hours=3),
            "end_time": base + timedelta(days=7, hours=6),
            "signup_deadline": base + timedelta(days=6, hours=20),
            "capacity": 30,
            "requires_review": True,
            "eligibility_note": "限大三及以上，且已修完《电路分析基础》。",
        },
        {
            # 演示 R-01/R-02/R-03：满员后进入候补、退出候补、空位自动递补
            "title": "摄影基础工作坊（名额有限）",
            "summary": "由摄影协会指导教师讲解构图与用光，需自备相机或手机。"
                       "名额已满，仍想参加的同学可加入候补，"
                       "有人退出时按候补顺序自动补位。",
            "location": "艺术楼 302 摄影教室",
            "category_id": category_ids.get("社团活动"),
            "start_time": base + timedelta(days=12, hours=2),
            "end_time": base + timedelta(days=12, hours=5),
            "signup_deadline": base + timedelta(days=11, hours=20),
            "capacity": 2,
        },
    ]

    created = []
    for plan in plans:
        activity = Activity(creator_id=teacher.id, **plan)
        db.session.add(activity)
        created.append(activity)
    db.session.flush()

    # 为「摄影基础工作坊」预置报名数据：2 人正式参加（占满上限）、1 人候补。
    # 这样打开系统即可直接演示「取消报名 → 空位自动递补给候补第一位」。
    demo = next((a for a in created if a.title.startswith("摄影基础工作坊")), None)
    if demo is not None:
        for username, status in [
            ("linxiangyu", REG_APPROVED),
            ("chenjiahe", REG_APPROVED),
            ("zhaoyiming", REG_WAITLIST),
        ]:
            user = User.query.filter_by(username=username).first()
            if user is not None:
                db.session.add(
                    Registration(activity_id=demo.id, user_id=user.id, status=status)
                )

    db.session.commit()
    return len(plans)


def main(argv=None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    reset = "--reset" in argv

    app = create_app()
    with app.app_context():
        if reset:
            db.drop_all()
            db.create_all()
            print("已清空并重建所有数据表。")
        print(f"分类新增 {seed_categories()} 条")
        print(f"用户新增 {seed_users()} 条")
        print(f"示例活动新增 {seed_activities()} 条")
        print(f"演示账号口令统一为：{DEMO_PASSWORD}")
        print("演示账号：wangtairan / tangjiahan（教师）、linxiangyu 等（学生）、admin（管理员）")


if __name__ == "__main__":
    main()

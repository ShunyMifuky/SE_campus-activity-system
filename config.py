"""校园活动管理系统 V1.0 —— 全局配置。

V1.0 的重要约束之一是「单机可运行、不依赖任何外部服务」，因此数据库固定
使用项目内的 SQLite 文件，密钥允许通过环境变量覆盖而不写死在代码里。
"""

import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    # 生产环境应通过环境变量注入；仓库内不提交真实密钥
    SECRET_KEY = os.environ.get("SECRET_KEY", "campus-activity-v1-dev-key")

    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(
        BASE_DIR, "instance", "campus.db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # 会话保持 8 小时，便于测试期间反复登录
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 8

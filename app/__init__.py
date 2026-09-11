"""校园活动管理系统 V1.0 —— 应用工厂。

V1.0 采用「单体应用 + 服务端渲染」结构，首要目标是把
「教师发布活动 → 学生浏览并报名」这条基本业务闭环真实跑通，
因此应用装配逻辑集中在 create_app()，便于按模块逐步接入 Blueprint。
"""

import os

from flask import Flask

from .extensions import db, login_manager


def create_app(config_object="config.Config"):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object)

    # SQLite 文件所在目录必须先存在，否则首次建库会失败
    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)

    @app.route("/healthz")
    def healthz():
        """最小可用性探针，供开发与验证阶段确认服务已启动。"""
        return {"status": "ok", "app": "校园活动管理系统", "version": "V1.0"}

    with app.app_context():
        db.create_all()

    return app

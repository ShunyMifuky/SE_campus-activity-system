"""蓝图注册与全局错误处理。"""

import os

from flask import Flask, render_template

from .extensions import db, login_manager


def create_app(config_object="config.Config"):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object)

    # SQLite 文件所在目录必须先存在，否则首次建库会失败
    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)

    from .activities import activities_bp
    from .admin import admin_bp
    from .auth import auth_bp
    from .main import main_bp
    from .notifications import notifications_bp
    from .registrations import registrations_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(activities_bp)
    app.register_blueprint(registrations_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")

    _register_error_handlers(app)
    _register_template_helpers(app)

    with app.app_context():
        db.create_all()

    return app


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(403)
    def forbidden(error):  # noqa: ARG001
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(error):  # noqa: ARG001
        return render_template("errors/404.html"), 404


def _register_template_helpers(app: Flask) -> None:
    """把模型中的状态标签注入模板，避免在 HTML 里硬编码中文业务文案。"""

    @app.context_processor
    def inject_labels():
        from flask_login import current_user

        from .models import REG_LABELS, ROLE_LABELS, STATUS_LABELS, unread_notification_count

        return {
            "ROLE_LABELS": ROLE_LABELS,
            "STATUS_LABELS": STATUS_LABELS,
            "REG_LABELS": REG_LABELS,
            # V3.0 R-14：导航栏未读角标；未登录时恒为 0
            "unread_count": unread_notification_count(current_user),
        }

    @app.template_global()
    def signup_token():
        """为每次渲染生成一个提交令牌（V3.0 R-10）。

        放在模板全局里，详情页直接调用；同一页面的重复提交携带同一令牌，
        服务端据此返回首次结果，而不是报「重复报名」。
        """
        from uuid import uuid4

        return uuid4().hex

    @app.template_filter("deadline_hint")
    def deadline_hint(value):
        """把报名截止时间说成人话（V3.0 R-16）。

        卡片上直接给「还剩 2 天 / 今天 18:00 截止」，用户不必点进详情算时间。
        """
        from .models import now

        if value is None:
            return ""
        delta = value - now()
        seconds = delta.total_seconds()
        if seconds < 0:
            return "已截止"
        if seconds < 3600:
            return f"剩 {max(int(seconds // 60), 1)} 分钟"
        if seconds < 86400:
            return f"剩 {int(seconds // 3600)} 小时"
        days = int(seconds // 86400)
        if days <= 7:
            return f"剩 {days} 天"
        return value.strftime("%m-%d %H:%M")

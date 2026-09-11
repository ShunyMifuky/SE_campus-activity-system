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
    from .auth import auth_bp
    from .main import main_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(activities_bp)

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
        from .models import ROLE_LABELS, STATUS_LABELS

        return {"ROLE_LABELS": ROLE_LABELS, "STATUS_LABELS": STATUS_LABELS}

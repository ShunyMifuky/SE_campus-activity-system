"""扩展对象集中定义，避免 app 工厂与各 Blueprint 之间循环导入。"""

from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

login_manager = LoginManager()
# 未登录访问受保护页面时跳转到登录页
login_manager.login_view = "auth.login"
login_manager.login_message = "请先登录后再继续操作。"
login_manager.login_message_category = "warning"

"""权限装饰器（工程意图约束 C3：角色与资源归属双重校验）。

刻意不使用"前端隐藏按钮"的方式做权限控制——按钮隐藏只是体验，
真正的边界必须在服务端每一个入口处强制校验。
"""

from functools import wraps

from flask import abort, flash, redirect, request, url_for
from flask_login import current_user

from .models import ROLE_TEACHER


def login_required_view(view):
    """要求已登录，未登录时跳转登录页并记住来源地址。"""

    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            flash("请先登录后再继续操作。", "warning")
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapper


def role_required(*roles):
    """要求已登录且角色属于 roles，否则返回 403。"""

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                flash("请先登录后再继续操作。", "warning")
                return redirect(url_for("auth.login", next=request.path))
            if current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapper

    return decorator


def teacher_required(view):
    """仅活动组织教师可访问。"""
    return role_required(ROLE_TEACHER)(view)


def student_required(view):
    """仅学生可访问。"""
    from .models import ROLE_STUDENT

    return role_required(ROLE_STUDENT)(view)

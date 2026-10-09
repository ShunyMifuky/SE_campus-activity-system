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


def admin_required(view):
    """仅系统管理员可访问（V2.0 新增，R-09）。

    管理员负责平台账号与活动秩序，不介入具体报名业务；
    因此管理员的入口单独用本装饰器，不复用教师权限。
    """
    from .models import ROLE_ADMIN

    return role_required(ROLE_ADMIN)(view)


def ensure_resource_owner(resource, owner_field: str = "creator_id") -> None:
    """资源归属校验（约束 C3 的后半段）。

    角色校验只能回答"是不是教师"，回答不了"这是不是你的活动"。
    只做角色校验时，任何教师只要把 URL 里的活动 id 换成别人的，
    就能编辑、下架或查看他人活动的报名名单——因此归属必须单独校验。
    """
    if resource is None or getattr(resource, owner_field, None) != current_user.id:
        abort(403)

"""注册 / 登录 / 登出（REQ-01）。

安全要点：
  - 密码只以哈希形式入库（工程意图约束 C1）
  - 登录失败统一提示"账号或密码不正确"，不暴露账号是否存在
  - 登录后的跳转地址只接受站内相对路径，避免开放重定向
"""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from ..extensions import db
from ..models import ROLE_LABELS, ROLE_STUDENT, User

auth_bp = Blueprint("auth", __name__, template_folder="../templates")

MIN_PASSWORD_LENGTH = 6
MAX_PASSWORD_LENGTH = 64


def _validate_registration(form) -> list:
    """校验注册表单，返回错误信息列表（为空表示通过）。"""
    errors = []

    username = (form.get("username") or "").strip()
    real_name = (form.get("real_name") or "").strip()
    password = form.get("password") or ""
    confirm = form.get("confirm_password") or ""
    role = form.get("role") or ROLE_STUDENT

    if not username:
        errors.append("账号不能为空。")
    elif len(username) < 3 or len(username) > 50:
        errors.append("账号长度需为 3~50 个字符。")
    elif User.query.filter_by(username=username).first() is not None:
        errors.append("该账号已被注册，请更换。")

    if not real_name:
        errors.append("姓名不能为空。")

    if len(password) < MIN_PASSWORD_LENGTH:
        errors.append(f"密码长度不能少于 {MIN_PASSWORD_LENGTH} 位。")
    elif len(password) > MAX_PASSWORD_LENGTH:
        errors.append(f"密码长度不能超过 {MAX_PASSWORD_LENGTH} 位。")

    if password != confirm:
        errors.append("两次输入的密码不一致。")

    if role not in ROLE_LABELS:
        errors.append("请选择有效的用户身份。")

    return errors


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("activities.list_activities"))

    form = request.form
    if request.method == "POST":
        errors = _validate_registration(form)
        if errors:
            for message in errors:
                flash(message, "danger")
        else:
            user = User(
                username=form["username"].strip(),
                real_name=form["real_name"].strip(),
                student_no=(form.get("student_no") or "").strip(),
                role=form["role"],
            )
            # 只存哈希，不存明文
            user.set_password(form["password"])
            db.session.add(user)
            db.session.commit()
            flash("注册成功，请使用新账号登录。", "success")
            return redirect(url_for("auth.login"))

    return render_template("auth/register.html", roles=ROLE_LABELS)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("activities.list_activities"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user = User.query.filter_by(username=username).first()

        if user is None or not user.check_password(password):
            flash("账号或密码不正确。", "danger")
        else:
            login_user(user, remember=bool(request.form.get("remember")))
            flash(f"欢迎回来，{user.real_name}（{user.role_label}）。", "success")

            next_url = request.args.get("next") or request.form.get("next")
            if next_url and next_url.startswith("/") and not next_url.startswith("//"):
                return redirect(next_url)
            return redirect(url_for("activities.list_activities"))

    return render_template("auth/login.html", next=request.args.get("next", ""))


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("已退出登录。", "info")
    return redirect(url_for("activities.list_activities"))

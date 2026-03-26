"""Authentication routes — login / logout."""

from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user

bp = Blueprint('auth', __name__)


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        from uwb_web.models import User
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            next_page = request.args.get('next') or url_for('dashboard.index')
            return redirect(next_page)
        flash('Invalid username or password.', 'error')
    return render_template('login.html')


@bp.route('/logout', methods=['POST'])
def logout():
    logout_user()
    return redirect(url_for('auth.login'))

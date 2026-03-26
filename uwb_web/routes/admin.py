"""Admin routes — user management (admin-only)."""

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import current_user
from uwb_web.db import db
from uwb_web.models import User

bp = Blueprint('admin', __name__, url_prefix='/admin')


def _require_admin():
    if not current_user.is_authenticated or not current_user.is_admin:
        abort(403)


@bp.before_request
def check_admin():
    _require_admin()


@bp.route('/')
def index():
    users = User.query.order_by(User.id).all()
    return render_template('admin.html', users=users)


@bp.route('/users/create', methods=['POST'])
def create_user():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    is_admin = request.form.get('is_admin') == '1'

    if not username or not password:
        flash('Username and password are required.', 'error')
        return redirect(url_for('admin.index'))

    if len(password) < 4:
        flash('Password must be at least 4 characters.', 'error')
        return redirect(url_for('admin.index'))

    if User.query.filter_by(username=username).first():
        flash(f'User "{username}" already exists.', 'error')
        return redirect(url_for('admin.index'))

    user = User(username=username, is_admin=is_admin)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    flash(f'User "{username}" created.', 'success')
    return redirect(url_for('admin.index'))


@bp.route('/users/<int:uid>/delete', methods=['POST'])
def delete_user(uid):
    user = db.session.get(User, uid)
    if not user:
        flash('User not found.', 'error')
        return redirect(url_for('admin.index'))
    if user.id == current_user.id:
        flash('You cannot delete yourself.', 'error')
        return redirect(url_for('admin.index'))
    db.session.delete(user)
    db.session.commit()
    flash(f'User "{user.username}" deleted.', 'success')
    return redirect(url_for('admin.index'))


@bp.route('/users/<int:uid>/toggle-admin', methods=['POST'])
def toggle_admin(uid):
    user = db.session.get(User, uid)
    if not user:
        flash('User not found.', 'error')
        return redirect(url_for('admin.index'))
    if user.id == current_user.id:
        flash('You cannot change your own admin status.', 'error')
        return redirect(url_for('admin.index'))
    user.is_admin = not user.is_admin
    db.session.commit()
    role = 'admin' if user.is_admin else 'regular user'
    flash(f'"{user.username}" is now {role}.', 'success')
    return redirect(url_for('admin.index'))


@bp.route('/users/<int:uid>/reset-password', methods=['POST'])
def reset_password(uid):
    user = db.session.get(User, uid)
    if not user:
        flash('User not found.', 'error')
        return redirect(url_for('admin.index'))
    new_pw = request.form.get('new_password', '')
    if len(new_pw) < 4:
        flash('Password must be at least 4 characters.', 'error')
        return redirect(url_for('admin.index'))
    user.set_password(new_pw)
    db.session.commit()
    flash(f'Password reset for "{user.username}".', 'success')
    return redirect(url_for('admin.index'))

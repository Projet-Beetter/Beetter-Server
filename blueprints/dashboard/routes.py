from flask import render_template, request, jsonify, flash, redirect, url_for, abort
from flask_login import login_required, current_user
from ..utils.influxdb import list_beehives, query_chart_data
from ...models import db, ApiKey, User
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SubmitField
from wtforms.validators import DataRequired, Length, Optional
from . import dashboard_bp


class LocalInstanceForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(1, 100)])
    description = TextAreaField('Description', validators=[Optional(), Length(max=500)])
    submit = SubmitField('Register instance')


@dashboard_bp.route('/')
@login_required
def index():
    beehives = {}
    try:
        beehives = list_beehives()
    except Exception:
        pass
    instances = ApiKey.query.filter_by(user_id=current_user.id).order_by(ApiKey.created_at).all()
    form = LocalInstanceForm()
    return render_template('dashboard/index.html', beehives=beehives, instances=instances, form=form)


@dashboard_bp.route('/instances/new', methods=['POST'])
@login_required
def new_instance():
    form = LocalInstanceForm()
    if form.validate_on_submit():
        instance = ApiKey(
            name=form.name.data,
            description=form.description.data or None,
            user_id=current_user.id,
        )
        db.session.add(instance)
        db.session.commit()
        flash(
            f'Instance <strong>{instance.name}</strong> registered — '
            f'copy the API key now, it will not be shown again:<br>'
            f'<code class="user-select-all">{instance.key}</code>',
            'success',
        )
    return redirect(url_for('dashboard.index'))


@dashboard_bp.route('/instances/<int:instance_id>/toggle', methods=['POST'])
@login_required
def toggle_instance(instance_id):
    instance = ApiKey.query.filter_by(id=instance_id, user_id=current_user.id).first_or_404()
    instance.enabled = not instance.enabled
    db.session.commit()
    state = 'enabled' if instance.enabled else 'disabled'
    flash(f'Instance "{instance.name}" {state}.', 'info')
    return redirect(url_for('dashboard.index'))


@dashboard_bp.route('/instances/<int:instance_id>/delete', methods=['POST'])
@login_required
def delete_instance(instance_id):
    instance = ApiKey.query.filter_by(id=instance_id, user_id=current_user.id).first_or_404()
    db.session.delete(instance)
    db.session.commit()
    flash(f'Instance "{instance.name}" deleted.', 'info')
    return redirect(url_for('dashboard.index'))


@dashboard_bp.route('/beehives/<beehive_id>/chart-data')
@login_required
def chart_data(beehive_id):
    range_str = request.args.get('range', '24h')
    try:
        data = query_chart_data(beehive_id, range_str)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return jsonify(data)


# ── User management (admin only) ───────────────────────────────────────────────

@dashboard_bp.route('/users')
@login_required
def users():
    if not current_user.is_admin:
        abort(403)
    all_users = User.query.order_by(User.created_at).all()
    return render_template('dashboard/users.html', users=all_users)


@dashboard_bp.route('/users/<int:user_id>/toggle-role', methods=['POST'])
@login_required
def toggle_user_role(user_id):
    if not current_user.is_admin:
        abort(403)
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot change your own role.', 'warning')
        return redirect(url_for('dashboard.users'))
    user.role = 'viewer' if user.role == 'admin' else 'admin'
    db.session.commit()
    flash(f'"{user.username}" is now {user.role}.', 'success')
    return redirect(url_for('dashboard.users'))


@dashboard_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        abort(403)
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot delete yourself.', 'warning')
        return redirect(url_for('dashboard.users'))
    db.session.delete(user)
    db.session.commit()
    flash(f'User "{user.username}" deleted.', 'info')
    return redirect(url_for('dashboard.users'))

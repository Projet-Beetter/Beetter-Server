from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from ..utils.influxdb import list_beehives, query_chart_data
from ...models import db, ApiKey
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired, Length
from . import dashboard_bp


class ApiKeyForm(FlaskForm):
    name = StringField('Key name', validators=[DataRequired(), Length(1, 100)])
    submit = SubmitField('Generate key')


@dashboard_bp.route('/')
@login_required
def index():
    beehives = {}
    try:
        beehives = list_beehives()
    except Exception:
        pass
    api_keys = ApiKey.query.filter_by(user_id=current_user.id).order_by(ApiKey.created_at).all()
    form = ApiKeyForm()
    return render_template('dashboard/index.html', beehives=beehives, api_keys=api_keys, form=form)


@dashboard_bp.route('/api-keys/new', methods=['POST'])
@login_required
def new_api_key():
    form = ApiKeyForm()
    if form.validate_on_submit():
        key = ApiKey(name=form.name.data, user_id=current_user.id)
        db.session.add(key)
        db.session.commit()
        flash(f'Key created — copy it now, it will not be shown again: {key.key}', 'success')
    return redirect(url_for('dashboard.index'))


@dashboard_bp.route('/api-keys/<int:key_id>/delete', methods=['POST'])
@login_required
def delete_api_key(key_id):
    key = ApiKey.query.filter_by(id=key_id, user_id=current_user.id).first_or_404()
    db.session.delete(key)
    db.session.commit()
    flash(f'API key "{key.name}" deleted.', 'info')
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

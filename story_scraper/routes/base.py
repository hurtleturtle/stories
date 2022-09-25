from flask import Blueprint, render_template


bp = Blueprint('base', __name__, template_folder='templates/base')


@bp.route('')
def index():
    return render_template('base.html')
from flask import Flask, render_template


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True, template_folder='routes/templates')

    if test_config:
        app.config.from_mapping(test_config)

    @app.route('/')
    def index():
        return render_template('base.html')

    return app
from flask import Flask


def create_app():
    app = Flask(__name__, instance_relative_config=True, template_folder='routes/templates')

    return app
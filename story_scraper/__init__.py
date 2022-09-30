from flask import Flask


def create_app():
    app = Flask(__name__, instance_relative_config=True, template_folder='routes/templates')


    from story_scraper.routes import base
    app.register_blueprint(base.bp)

    return app
import os
import logging
from flask import Flask

from app.extensions import db, migrate
from app.routes import bp
from app.cli import scan_all_users_command, scan_user_command

def create_app(config_file='config.py'):
    app = Flask(__name__)

    # Load configuration
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    config_path = os.path.join(base_dir, config_file)

    if os.path.exists(config_path):
        app.config.from_pyfile(config_path)
    else:
        print(f"Warning: Config file {config_path} not found.")

    # --- Logging Configuration ---
    log_level_str = app.config.get('LOG_LEVEL', 'INFO').upper()
    log_level = getattr(logging, log_level_str, logging.INFO)

    logging.basicConfig(level=log_level,
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                        handlers=[
                            logging.FileHandler(app.config.get('LOG_FILE', 'app.log')),
                            logging.StreamHandler()
                        ])

    app.logger.setLevel(log_level)

    if not app.debug:
        werkzeug_logger = logging.getLogger('werkzeug')
        werkzeug_logger.setLevel(log_level)

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)

    # Register Blueprints
    app.register_blueprint(bp)

    # Register CLI commands
    app.cli.add_command(scan_all_users_command)
    app.cli.add_command(scan_user_command)

    # Globals
    # Use constants instead of hardcoded lists
    from app.constants import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, MEDIA_EXTENSIONS
    app.jinja_env.globals['IMAGE_EXTENSIONS'] = IMAGE_EXTENSIONS
    app.jinja_env.globals['VIDEO_EXTENSIONS'] = VIDEO_EXTENSIONS
    app.jinja_env.globals['MEDIA_EXTENSIONS'] = MEDIA_EXTENSIONS

    return app

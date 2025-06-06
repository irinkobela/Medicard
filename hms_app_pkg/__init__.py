# hms_app_pkg/__init__.py
from flask import Flask , jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate # Optional: For database migrations
from dotenv import load_dotenv
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import NotFound
from .sockets import socketio


# Load environment variables from .env file.
# This should be called as early as possible.
# Having it here means it's loaded when hms_app_pkg is imported.
load_dotenv()

# Import configurations
# This assumes DevelopmentConfig, etc. are directly importable from .config
from .config import DevelopmentConfig, ProductionConfig, TestingConfig, Config # Ensure Config is imported if get_config is not used.
# OR if you prefer using the get_config() helper from your config.py:
# from .config import get_config


db = SQLAlchemy()
migrate = Migrate() 

def create_app(config_name='development'):
    """
    Application factory function.
    """
    app = Flask(__name__)

    # Load configuration based on the environment
    # If using get_config() from config.py:
    # app.config.from_object(get_config(config_name))
    # else, your existing logic is fine:
    if config_name == 'production':
        app.config.from_object(ProductionConfig)
    elif config_name == 'testing':
        app.config.from_object(TestingConfig)
    else: # Default to development
        app.config.from_object(DevelopmentConfig)

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    socketio.init_app(app)


    # Import and register Blueprints
    from .auth.routes import auth_bp
    app.register_blueprint(auth_bp, url_prefix='/api/auth')

    from .patient_chart.routes import patient_chart_bp
    app.register_blueprint(patient_chart_bp, url_prefix='/api')

    from .cpoe.routes import cpoe_bp
    app.register_blueprint(cpoe_bp, url_prefix='/api')

    from .admin.routes import admin_bp
    app.register_blueprint(admin_bp, url_prefix='/api/admin')

    from .medications.routes import medications_bp 
    app.register_blueprint(medications_bp, url_prefix='/api')

    from .results.routes import results_bp 
    app.register_blueprint(results_bp, url_prefix='/api')

    from .tasks.routes import tasks_bp 
    app.register_blueprint(tasks_bp, url_prefix='/api') # Suggestion: Removed trailing slash for consistency

    from .vitalsigns.routes import vitalsigns_bp # Ensure this name 'vitalsigns_bp' matches the variable in vitalsigns/routes.py
    app.register_blueprint(vitalsigns_bp, url_prefix='/api')

    from .rounds.routes import rounds_bp
    app.register_blueprint(rounds_bp, url_prefix='/api')

    from .handoff.routes import handoff_bp
    app.register_blueprint(handoff_bp, url_prefix='/api')

    from .flags.routes import flags_bp
    app.register_blueprint(flags_bp, url_prefix='/api')

    from .discharge.routes import discharge_bp
    app.register_blueprint(discharge_bp, url_prefix='/api')

    from .schedule.routes import schedule_bp
    app.register_blueprint(schedule_bp, url_prefix='/api')

    from .notifications.routes import notifications_bp
    app.register_blueprint(notifications_bp, url_prefix='/api')

    from .reports.routes import reports_bp
    app.register_blueprint(reports_bp, url_prefix='/api')

    from .dashboard.routes import dashboard_bp
    app.register_blueprint(dashboard_bp, url_prefix='/api')

    from .cds.routes import cds_bp
    app.register_blueprint(cds_bp, url_prefix='/api')

    from .mar.routes import mar_bp
    app.register_blueprint(mar_bp, url_prefix='/api')

    from .timeline.routes import timeline_bp
    app.register_blueprint(timeline_bp, url_prefix='/api')
    
    #  from .stats.routes import stats_bp
    # app.register_blueprint(stats_bp, url_prefix='/api')

    # from .profile.routes import profile_bp
    # app.register_blueprint(profile_bp, url_prefix='/api/profile')


    @app.route('/health')
    def health_check():
        return "HMS App is healthy!", 200
    
    # This section adds centralized error handling for the whole app.
    @app.errorhandler(SQLAlchemyError)
    def handle_database_error(e):
        """Catches and handles all SQLAlchemy-related database errors."""
        # Log the error so you can see it in your server logs
        app.logger.error(f"Database Error: {e}")
        # Rollback the session to prevent hanging transactions
        db.session.rollback()
        # Return a clean, user-friendly JSON response
        return jsonify({"error": "A database error occurred."}), 500

    @app.errorhandler(NotFound)
    def handle_not_found_error(e):
        """Handles 404 Not Found errors, like when a URL is wrong."""
        app.logger.warning(f"Not Found Error: {e}")
        return jsonify({"error": "The requested resource was not found."}), 404

    @app.errorhandler(Exception)
    def handle_generic_error(e):
        """A fallback handler for any other unexpected errors."""
        # Log the full traceback to help with debugging
        app.logger.error(f"An unexpected error occurred: {e}", exc_info=True)
        # Return a generic error message so we don't expose internal details
        return jsonify({"error": "An unexpected server error occurred."}), 500
    return app

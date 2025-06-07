# hms_app_pkg/__init__.py

from flask import Flask, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from dotenv import load_dotenv
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import NotFound

# Load environment variables from .env file.
load_dotenv()

# Import configurations
from .config import DevelopmentConfig, ProductionConfig, TestingConfig

# Initialize extensions at the top level, but without an app context.
# This is a standard pattern to avoid circular imports.
db = SQLAlchemy()
migrate = Migrate()
# Note: socketio is now imported and initialized inside create_app.


def create_app(config_name='development'):
    """
    Application factory function.
    """
    app = Flask(__name__)

    # Load configuration based on the environment
    if config_name == 'production':
        app.config.from_object(ProductionConfig)
    elif config_name == 'testing':
        app.config.from_object(TestingConfig)
    else: # Default to development
        app.config.from_object(DevelopmentConfig)

    # Initialize extensions with the app context
    db.init_app(app)
    migrate.init_app(app, db)
    
    # --- THIS IS THE FIX ---
    # We import and initialize socketio here, after the app is created,
    # to break the circular import loop.
    from .sockets import socketio
    socketio.init_app(app)
    # -----------------------

    # --- Import and register Blueprints INSIDE create_app ---
    # This also prevents circular imports.
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
    app.register_blueprint(tasks_bp, url_prefix='/api')

    from .vitalsigns.routes import vitalsigns_bp
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

    # Register audit listeners
    from .audit.listeners import register_audit_listeners
    register_audit_listeners()

    @app.route('/health')
    def health_check():
        return "HMS App is healthy!", 200
    
    # Centralized error handling
    @app.errorhandler(SQLAlchemyError)
    def handle_database_error(e):
        app.logger.error(f"Database Error: {e}")
        db.session.rollback()
        return jsonify({"error": "A database error occurred."}), 500

    @app.errorhandler(NotFound)
    def handle_not_found_error(e):
        app.logger.warning(f"Not Found Error: {e}")
        return jsonify({"error": "The requested resource was not found."}), 404

    @app.errorhandler(Exception)
    def handle_generic_error(e):
        app.logger.error(f"An unexpected error occurred: {e}", exc_info=True)
        return jsonify({"error": "An unexpected server error occurred."}), 500
        
    return app
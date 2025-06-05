# hms_app_pkg/__init__.py
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate # type: ignore # Optional: For database migrations

# Import configurations - This assumes DevelopmentConfig, etc. are directly importable
# If you used the get_config() helper in your config.py, you'd import that instead.
# Let's assume your config.py makes these classes available for import.
from .config import DevelopmentConfig, ProductionConfig, TestingConfig 

db = SQLAlchemy()
migrate = Migrate() # Optional

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

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db) # Optional: if you want to use Flask-Migrate

    # Import and register Blueprints that we HAVE defined
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
    app.register_blueprint(tasks_bp, url_prefix='/api/')
    
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


    # --- COMMENT OUT NEW, UNDEFINED BLUEPRINTS FOR NOW ---
    # from .schedule.routes import schedule_bp
    # app.register_blueprint(schedule_bp, url_prefix='/api')

    # from .notifications.routes import notifications_bp
    # app.register_blueprint(notifications_bp, url_prefix='/api')

    # from .reports.routes import reports_bp
    # app.register_blueprint(reports_bp, url_prefix='/api')

    # from .stats.routes import stats_bp
    # app.register_blueprint(stats_bp, url_prefix='/api')

    # from .profile.routes import profile_bp
    # app.register_blueprint(profile_bp, url_prefix='/api/profile')
    # --- END OF COMMENTED OUT BLUEPRINTS ---

    with app.app_context():
        db.create_all()

    @app.route('/health')
    def health_check():
        return "HMS App is healthy!", 200

    return app

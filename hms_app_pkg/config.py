import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'd64fde6fe18c685d976f9b12dd5a5d016575b03ca03bf3ed'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///hms_dev.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    _jwt_secret_key_value = os.environ.get('JWT_SECRET_KEY') or 'c57662138895c0a955c3b8a3875695b8629976542862d732e3961c4e1afe14c7' # Your key
    print(f"DEBUG: Config class JWT_SECRET_KEY being set to: '{_jwt_secret_key_value}'") # DEBUG PRINT
    JWT_SECRET_KEY = _jwt_secret_key_value
    JWT_ALGORITHM = 'HS256'
    JWT_EXPIRATION_MINUTES = 60

class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get('DEV_DATABASE_URL') or 'sqlite:///hms_dev.db'
    JWT_REFRESH_TOKEN_EXPIRES_DAYS = 7  # Or your preferred duration
    PASSWORD_RESET_TOKEN_EXPIRES_HOURS = 1
    FRONTEND_URL = os.environ.get('FRONTEND_URL') or 'http://localhost:3000' # Your frontend app's URL
    
class TestingConfig(Config):
    """Testing configuration."""
    DEBUG = True
    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.environ.get('TEST_DATABASE_URL') or 'sqlite:///hms_test.db' # Use a separate DB for tests
    JWT_EXPIRATION_MINUTES = 1 # Short token life for testing

class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    # Example for PostgreSQL in production, fetched from environment variables
    # SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'postgresql://user:password@host:port/prod_db_name'
    # Ensure SECRET_KEY and JWT_SECRET_KEY are ALWAYS set from environment variables in production

# Helper function to get the correct config based on an environment variable
def get_config():
    env = os.environ.get('FLASK_ENV', 'development').lower()
    if env == 'production':
        return ProductionConfig
    elif env == 'testing':
        return TestingConfig
    return DevelopmentConfig

# To make it easy to import directly
# from config import DevelopmentConfig etc.
# Or use app.config.from_object(get_config())

# hms_app_pkg/config.py
import os
from datetime import timedelta

# Load environment variables from .env file if python-dotenv is installed
# This is usually done in run.py or the app factory now.
# from dotenv import load_dotenv
# load_dotenv() # Not strictly needed here if loaded in run.py or app factory

class Config:
    """Base configuration settings."""
    # Application Security
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'you_REALLY_should_set_a_secret_key_in_env'
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY') or 'you_REALLY_should_set_a_JWT_secret_key_in_env'
    JWT_ALGORITHM = 'HS256'
    JWT_EXPIRATION_MINUTES = int(os.environ.get('JWT_EXPIRATION_MINUTES', 60))
    JWT_REFRESH_TOKEN_EXPIRES_DAYS = int(os.environ.get('JWT_REFRESH_TOKEN_EXPIRES_DAYS', 7))
    
    # Password Reset
    PASSWORD_RESET_TOKEN_EXPIRES_HOURS = int(os.environ.get('PASSWORD_RESET_TOKEN_EXPIRES_HOURS', 1))

    # Database
    # Default to SQLite if DATABASE_URL is not set in the environment
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///hms_default.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Frontend URL
    FRONTEND_URL = os.environ.get('FRONTEND_URL') or 'http://localhost:3000'
    
    CACHE_TYPE = 'RedisCache'
    CACHE_REDIS_URL = os.environ.get('REDIS_URL') or 'redis://localhost:6379/0'

class DevelopmentConfig(Config):
    """Development-specific configuration."""
    DEBUG = True
    # Override DATABASE_URL for development if DEV_DATABASE_URL is set, else use Config's default or DATABASE_URL
    SQLALCHEMY_DATABASE_URI = os.environ.get('DEV_DATABASE_URL') or os.environ.get('DATABASE_URL') or 'sqlite:///hms_dev.db'
    # For development, you might want shorter token expiries for easier testing of refresh logic
    # JWT_EXPIRATION_MINUTES = 5
    # JWT_REFRESH_TOKEN_EXPIRES_DAYS = 1


class TestingConfig(Config):
    """Testing-specific configuration."""
    TESTING = True
    DEBUG = True # Often useful to have debug true for tests to get more error info
    # Use a separate database for testing (in-memory SQLite or a dedicated test DB file)
    SQLALCHEMY_DATABASE_URI = os.environ.get('TEST_DATABASE_URL') or 'sqlite:///hms_test.db'
    JWT_EXPIRATION_MINUTES = 1 # Very short token life for testing expiry
    JWT_REFRESH_TOKEN_EXPIRES_DAYS = 1 # Short refresh token life for testing
    PASSWORD_RESET_TOKEN_EXPIRES_HOURS = 1 # Can be short for testing


class ProductionConfig(Config):
    """Production-specific configuration."""
    DEBUG = False
    TESTING = False

    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///prod_fallback.db'  # Fallback for local testing

    if Config.SECRET_KEY == 'you_REALLY_should_set_a_secret_key_in_env':
        raise ValueError("SECRET_KEY not set via environment variable for production")
    if Config.JWT_SECRET_KEY == 'you_REALLY_should_set_a_JWT_secret_key_in_env':
        raise ValueError("JWT_SECRET_KEY not set via environment variable for production")


def get_config():
    """Helper function to get the correct config class based on FLASK_ENV."""
    env = os.environ.get('FLASK_ENV', 'development').lower()
    if env == 'production':
        return ProductionConfig
    elif env == 'testing':
        return TestingConfig
    return DevelopmentConfig


# run.py
import os
from hms_app_pkg import create_app # We will create this function in hms_app_pkg/__init__.py

# Determine the configuration environment
# You can set FLASK_ENV in your terminal:
# export FLASK_ENV=development (macOS/Linux)
# set FLASK_ENV=development (Windows)
# If not set, it defaults to 'development' in create_app
config_name = os.environ.get('FLASK_ENV', 'development')

app = create_app(config_name)

if __name__ == '__main__':
    # The host and port can also be configured or taken from environment variables
    app.run(host='0.0.0.0', port=5000)

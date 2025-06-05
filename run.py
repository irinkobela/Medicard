# run.py
import os
from dotenv import load_dotenv # Import at the top

load_dotenv() # Load variables from .env file into environment

from hms_app_pkg import create_app

config_name = os.environ.get('FLASK_ENV', 'development')
app = create_app(config_name)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
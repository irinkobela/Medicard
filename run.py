# run.py
import os
from dotenv import load_dotenv
load_dotenv()

from hms_app_pkg import create_app

config_name = os.environ.get('FLASK_ENV', 'development')
print(f"DEBUG run.py: FLASK_ENV is '{os.environ.get('FLASK_ENV')}', config_name is '{config_name}'") # ADD THIS LINE
app = create_app(config_name)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
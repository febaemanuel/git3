"""Single source of truth for Flask extensions.

Instances are created without binding to an app; bind via ``init_app(app)``
inside the application factory.
"""

from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect


db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()

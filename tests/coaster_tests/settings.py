"""
Note: This is a test config file used by test_app.py.
"""
SETTINGS_KEY = 'settings'
ADMINS = ['test@example.com']
DEFAULT_MAIL_SENDER = ('Hasgeek', 'test@example.com')
MAIL_SERVER = 'mail.example.com'
MAIL_PORT = 587
MAIL_USERNAME = 'username'
MAIL_PASSWORD = 'PASSWORD'  # nosec
SECRET_KEY = 'd vldvnvnvjn'  # nosec
SQLALCHEMY_DATABASE_URI = 'postgresql+psycopg://localhost/coaster_test'

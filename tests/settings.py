"""
Note: This is a test config file used by test_app.py.
"""
SETTINGS_KEY = 'settings'
ADMINS = ['test@example.com']
DEFAULT_MAIL_SENDER = ('Hasgeek', 'test@example.com')
MAIL_SERVER = 'mail.example.com'
MAIL_PORT = 587
MAIL_USERNAME = 'username'
MAIL_PASSWORD = 'PASSWORD'  # nosec  # noqa: S105
SECRET_KEY = 'd vldvnvnvjn'  # nosec  # noqa: S105
SQLALCHEMY_DATABASE_URI = 'postgresql:///coaster_test'

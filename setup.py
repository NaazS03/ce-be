from setuptools import setup

setup(
    name='backend',
    packages=['backend'],
    include_package_data=True,
    install_requires=[
        'Flask',
        'Flask-SQLAlchemy',
        'psycopg2-binary',
        'pylint-flask',
        'flask_marshmallow',
        'flask-cors',
        'gevent',
        'gunicorn',
        'marshmallow-sqlalchemy',
        'python-dotenv',
        'email_validator',
        'flask-bcrypt',
        'pyjwt==1.4.2',
        'flask-session',
        'flask-mail',
        'pytest',
        'pytest-flask',
        'pytest-flask-sqlalchemy'
    ],
)

web: gunicorn "originalentry.app:create_app()" -c gunicorn.conf.py
release: ORIGINALENTRY_USE_DIRECT_DB=1 FLASK_APP=originalentry.app:create_app flask db upgrade

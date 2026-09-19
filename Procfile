web: gunicorn "parchment.app:create_app()" -c gunicorn.conf.py
release: PARCHMENT_USE_DIRECT_DB=1 FLASK_APP=parchment.app:create_app flask db upgrade

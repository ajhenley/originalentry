"""Gunicorn configuration for the Heroku web dyno (T13, T13.1).

Two workers with four threads each, a 25-second timeout kept under the router's 30 seconds, and
an access log that carries the method, the path **without its query string**, the status, the
duration and the request id — never the client IP and never the query string (T13.1, FERPA).
"""

import os

# 2 workers × 4 threads (WEB_CONCURRENCY lets Heroku scale workers to the dyno).
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
threads = int(os.environ.get("WEB_THREADS", "4"))
worker_class = "gthread"

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"

# Under the 30 s router limit; long operations run in browser batches or the CLI, not a request.
timeout = 25
graceful_timeout = 25
keepalive = 5

# Log to stdout/stderr for Heroku's log stream. Short retention lives in Postgres (activity_event,
# staff_action), so the access log deliberately omits the IP and the query string.
accesslog = "-"
errorlog = "-"
access_log_format = '%(m)s %(U)s %(s)s %(D)sµs req=%({x-request-id}i)s'

# The dyno filesystem is ephemeral; nothing is preloaded that would pin stale content.
preload_app = False

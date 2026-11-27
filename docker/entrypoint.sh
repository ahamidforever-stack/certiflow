#!/bin/sh
set -e
# install licensed fonts supplied by the office (never baked into the image)
if [ -d /fonts ] && ls /fonts/*.tt[fc] >/dev/null 2>&1; then
  certiflow fonts install /fonts >/dev/null
fi
case "$1" in
  web)
    certiflow web init-db
    exec uvicorn --factory certiflow.web.app:create_app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'
    ;;
  worker)
    exec celery -A certiflow.web.tasks worker --concurrency="${CERTIFLOW_WORKER_CONCURRENCY:-2}" --loglevel=INFO
    ;;
  *)
    exec "$@"
    ;;
esac

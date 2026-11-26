"""Leased processing worker with Prometheus metrics on port 9101."""
import os
import time
from prometheus_client import start_http_server
from .main import process_one

if __name__ == '__main__':
    port = int(os.environ.get('TOPTIGER_WORKER_METRICS_PORT', '9101'))
    start_http_server(port)
    print(f'TopTigerAI worker started; metrics on :{port}/metrics', flush=True)
    while True:
        if not process_one():
            time.sleep(1)

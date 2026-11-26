"""Development worker. Production will use Temporal for durable retries and leases."""
import time
from .main import process_one

if __name__ == '__main__':
    print('TopTigerAI worker started', flush=True)
    while True:
        if not process_one():
            time.sleep(1)

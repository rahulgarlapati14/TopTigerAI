"""Process-local Prometheus instrumentation; API and worker expose separate endpoints."""
from prometheus_client import Counter, Histogram, Gauge

JOBS_CLAIMED = Counter('toptiger_jobs_claimed_total', 'Jobs claimed by workers')
JOBS_SUCCEEDED = Counter('toptiger_jobs_succeeded_total', 'Successfully finalized jobs')
JOBS_RETRIED = Counter('toptiger_jobs_retried_total', 'Jobs queued for another attempt')
JOBS_FAILED = Counter('toptiger_jobs_failed_total', 'Jobs permanently failed')
PROCESSING_SECONDS = Histogram('toptiger_processing_seconds', 'Job processing time in seconds', buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300))
SESSION_COUNTS = Gauge('toptiger_sessions', 'Sessions in each state', ['state'])

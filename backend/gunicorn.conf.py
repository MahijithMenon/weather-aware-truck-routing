import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
# One process with threads: plans and forecasts are cached in process memory
# (LocMemCache), so the heatmap request must reach the process that made the plan.
workers = 1
threads = int(os.environ.get("GUNICORN_THREADS", "8"))
timeout = 120

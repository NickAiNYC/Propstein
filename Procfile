web: uvicorn api.main:app --host 0.0.0.0 --port $PORT
worker: python scripts/live_nba_sniper_worker.py
grader: python -m scripts.grade_arb_history --loop --interval 900

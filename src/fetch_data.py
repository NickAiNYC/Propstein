"""Download nflverse data. Run once; re-run weekly in season."""
import os, urllib.request
B = "https://github.com/nflverse/nflverse-data/releases/download"
D = os.path.join(os.path.dirname(__file__), "..", "data")
os.makedirs(D, exist_ok=True)
for y in range(2016, 2027):
    try:
        urllib.request.urlretrieve(f"{B}/stats_player/stats_player_week_{y}.parquet",
                                   os.path.join(D, f"stats_{y}.parquet"))
        print("ok", y)
    except Exception as e:
        print("skip", y, e)
urllib.request.urlretrieve("https://github.com/nflverse/nfldata/raw/master/data/games.csv",
                           os.path.join(D, "games.csv"))
print("ok games.csv")

# Roster, injury and depth-chart feeds for the current season.
for name, tag, fname in (("roster", "weekly_rosters", "roster_weekly"),
                         ("injuries", "injuries", "injuries"),
                         ("depth", "depth_charts", "depth_charts")):
    for y in (2025, 2026):
        try:
            urllib.request.urlretrieve(f"{B}/{tag}/{fname}_{y}.parquet",
                                       os.path.join(D, f"{name}_{y}.parquet"))
            print("ok", name, y)
        except Exception as e:
            print("skip", name, y, e)

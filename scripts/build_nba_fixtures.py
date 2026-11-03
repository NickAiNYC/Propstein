#!/usr/bin/env python3
"""Deterministic NBA fixture builder (offline, no network, no API key).

Builds the complete two-night research fixture set with REAL player names on
REAL late-October-2026 rosters (owner decision 2026-10-27, superseding the
audit-B1 anonymization — see docs/MULTISPORT.md §2):

  viewer/nba_slate_2026-10-22.json    opener night: BOS@NYK, DEN@OKC (29 rows)
  viewer/nba_games_2026-10-22.json    2 games
  viewer/nba_odds_2026-10-22.json     EV-ranked quotes at realistic prices
  viewer/nba_injuries_2026-10-22.json Tatum (public status) + two-way shuttle
  viewer/nba_slate_2026-10-23.json    full night: 10 games, 140 modeled rows
  viewer/nba_games_2026-10-23.json    10 games (all tips map to Oct 23 ET)
  viewer/nba_odds_2026-10-23.json     EV-ranked quotes at realistic prices
  viewer/nba_injuries_2026-10-23.json 3 availability items + beneficiaries

Honesty rules (all enforced on-item, kept from the fixture contract):
- every row/quote/item carries _fixture: true; quotes never claim
  verification; the RESEARCH FIXTURES banner stays on every page;
- stat lines are SYNTHETIC projections built around public per-game profiles —
  they are not sportsbook quotes and not scouting-grade research;
- injury statuses are real public reporting ONLY where marked (Tatum Achilles
  rehab); every other item's source says "not a real injury report";
- rosters are a late-Oct-2026 snapshot (2026 offseason verified: Giannis->MIA,
  LeBron->PHI, Turner->MIL, Kessler->LAL, Zubac->IND, Ayton->WAS); depth slots
  are approximate.

Re-running is idempotent: output is a pure function of the per-night seeds.
Usage: python3 scripts/build_nba_fixtures.py
"""
import json
import math
import os
import random
import re
from datetime import datetime, timezone
from statistics import NormalDist
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
VIEWER = os.path.join(HERE, "..", "viewer")
ET = ZoneInfo("America/New_York")
ND = NormalDist()
MARKETS = ("points", "rebounds", "assists", "threes", "pra")
BANNED = re.compile(r"\b(guaranteed|lock|locks|sure thing|banker|free money|can'?t lose|proven winner)\b", re.I)
NOTICE = "Research fixtures — synthetic model data for terminal validation. Not sportsbook quotes. Not for wagering decisions."
SYNTH_SOURCE = "PropWire synthetic fixture (not a sportsbook quote; unverified research data)"
INJ_SOURCE = "PropWire fixture availability report — synthetic, not a real injury report"

# (away, home, tip_et, venue)
OCT22_GAMES = [
    ("BOS", "NYK", "19:30", "Madison Square Garden"),
    ("DEN", "OKC", "22:00", "Paycom Center"),
]
OCT23_GAMES = [
    ("MIL", "CLE", "19:00", "Rocket Mortgage FieldHouse"),
    ("TOR", "BKN", "19:30", "Barclays Center"),
    ("IND", "PHI", "19:00", "Wells Fargo Center"),
    ("ORL", "MIA", "19:30", "Kaseya Center"),
    ("DET", "CHI", "20:00", "United Center"),
    ("SAS", "HOU", "20:00", "Toyota Center"),
    ("MEM", "NOP", "20:00", "Smoothie King Center"),
    ("UTA", "SAC", "22:00", "Golden 1 Center"),
    ("GSW", "LAC", "22:00", "Intuit Dome"),
    ("PHX", "LAL", "22:30", "Crypto.com Arena"),
]
OCT29_GAMES = [
    ("BOS", "PHI", "19:00", "Wells Fargo Center"),
    ("MIL", "NYK", "19:30", "Madison Square Garden"),
    ("CLE", "IND", "19:00", "Gainbridge Fieldhouse"),
    ("ORL", "MIA", "19:30", "Kaseya Center"),
    ("DET", "CHI", "20:00", "United Center"),
    ("SAS", "HOU", "20:00", "Toyota Center"),
    ("DEN", "OKC", "20:00", "Paycom Center"),
    ("PHX", "LAC", "22:00", "Intuit Dome"),
    ("GSW", "LAL", "22:30", "Crypto.com Arena"),
    ("UTA", "SAC", "22:00", "Golden 1 Center"),
]

# (name, pos, minutes, usage, pts, reb, ast, fg3[, status])
ROSTERS = {
    "BOS": [
        ("Jaylen Brown", "SG", 36.0, 0.315, 26.5, 6.2, 5.0, 2.4),
        ("Derrick White", "PG", 34.0, 0.245, 16.8, 4.5, 4.7, 3.4),
        ("Jayson Tatum", "SF", 32.0, 0.300, 27.5, 8.3, 5.5, 3.0, "OUT"),
        ("Payton Pritchard", "PG", 30.0, 0.220, 14.5, 4.0, 3.8, 3.6),
        ("Sam Hauser", "SF", 26.0, 0.150, 9.0, 3.8, 1.6, 2.6),
        ("Neemias Queta", "C", 24.0, 0.160, 8.5, 7.5, 1.8, 0.3),
        ("Josh Minott", "SF", 18.0, 0.130, 7.0, 3.5, 1.2, 0.8),
    ],
    "NYK": [
        ("Jalen Brunson", "PG", 36.0, 0.320, 28.5, 3.5, 7.5, 2.5),
        ("Karl-Anthony Towns", "C", 34.5, 0.300, 25.5, 12.5, 3.2, 2.2),
        ("Mikal Bridges", "SF", 35.5, 0.200, 16.5, 4.0, 3.5, 1.8),
        ("OG Anunoby", "SF", 35.0, 0.240, 17.5, 5.0, 2.6, 2.2),
        ("Josh Hart", "SG", 32.0, 0.170, 12.5, 8.0, 5.0, 1.0),
        ("Mitchell Robinson", "C", 24.0, 0.130, 6.5, 9.0, 0.8, 0.0),
        ("Deuce McBride", "PG", 22.0, 0.140, 8.5, 2.5, 3.5, 1.4),
    ],
    "DEN": [
        ("Nikola Jokic", "C", 36.0, 0.340, 28.5, 12.8, 10.8, 1.8),
        ("Jamal Murray", "PG", 34.5, 0.280, 22.0, 4.2, 6.5, 2.6),
        ("Aaron Gordon", "PF", 32.0, 0.210, 15.0, 5.8, 3.0, 1.4),
        ("Christian Braun", "SG", 33.0, 0.190, 14.5, 5.0, 2.6, 1.2),
        ("Cameron Johnson", "SF", 28.0, 0.170, 11.0, 3.8, 2.2, 2.2),
        ("Peyton Watson", "SF", 24.0, 0.140, 8.5, 3.5, 1.5, 0.9),
        ("Jonas Valanciunas", "C", 20.0, 0.150, 8.0, 6.5, 1.5, 0.0),
    ],
    "OKC": [
        ("Shai Gilgeous-Alexander", "PG", 36.0, 0.345, 32.5, 5.2, 6.4, 2.1),
        ("Jalen Williams", "SF", 35.0, 0.280, 22.5, 5.5, 5.2, 1.9),
        ("Chet Holmgren", "PF", 30.0, 0.220, 16.5, 8.8, 1.8, 1.6),
        ("Luguentz Dort", "SG", 28.0, 0.150, 9.5, 3.8, 1.5, 1.8),
        ("Isaiah Hartenstein", "C", 28.0, 0.170, 9.0, 8.5, 3.2, 0.2),
        ("Cason Wallace", "PG", 26.0, 0.140, 8.0, 3.0, 2.8, 1.3),
        ("Alex Caruso", "SG", 22.0, 0.120, 6.5, 2.8, 2.2, 1.1),
    ],
    "MIL": [
        ("Myles Turner", "C", 30.0, 0.240, 14.5, 7.0, 1.8, 1.6),
        ("Kyle Kuzma", "PF", 32.0, 0.250, 17.5, 6.5, 3.0, 1.5),
        ("Gary Trent Jr.", "SG", 30.0, 0.220, 13.5, 2.8, 1.8, 2.4),
        ("Caris LeVert", "SG", 28.0, 0.210, 13.0, 4.0, 4.2, 1.2),
        ("Kevin Porter Jr.", "PG", 26.0, 0.230, 14.0, 4.5, 5.0, 1.6),
        ("Kel'el Ware", "C", 24.0, 0.170, 10.5, 7.5, 1.0, 0.5),
        ("AJ Green", "SG", 22.0, 0.150, 8.0, 2.8, 1.5, 2.2),
    ],
    "CLE": [
        ("Donovan Mitchell", "SG", 35.5, 0.330, 27.5, 4.5, 5.0, 3.2),
        ("Evan Mobley", "PF", 33.0, 0.250, 19.0, 9.5, 3.5, 1.4),
        ("Darius Garland", "PG", 31.0, 0.260, 20.0, 2.8, 6.8, 2.8),
        ("Jarrett Allen", "C", 30.0, 0.180, 14.0, 10.0, 1.8, 0.0),
        ("De'Andre Hunter", "SF", 26.0, 0.170, 11.5, 4.0, 1.5, 1.2),
        ("Max Strus", "SF", 26.0, 0.160, 10.0, 4.5, 3.0, 2.4),
        ("Sam Merrill", "SG", 24.0, 0.150, 9.0, 2.5, 1.5, 2.6),
    ],
    "TOR": [
        ("Scottie Barnes", "PF", 36.5, 0.310, 21.5, 8.0, 6.0, 1.6),
        ("Brandon Ingram", "SF", 33.0, 0.280, 21.0, 5.5, 4.8, 1.6),
        ("RJ Barrett", "SF", 34.0, 0.250, 20.5, 6.0, 5.0, 1.6),
        ("Immanuel Quickley", "PG", 30.0, 0.220, 15.5, 3.8, 5.5, 2.6),
        ("Jakob Poeltl", "C", 29.0, 0.170, 12.0, 9.0, 2.5, 0.0),
        ("Collin Murray-Boyles", "PF", 20.0, 0.140, 8.0, 5.0, 1.8, 0.3),
        ("Jamal Shead", "PG", 20.0, 0.130, 7.0, 2.5, 3.5, 1.0),
    ],
    "BKN": [
        ("Nic Claxton", "C", 30.0, 0.200, 12.5, 9.5, 2.5, 0.0),
        ("Noah Clowney", "PF", 27.0, 0.190, 13.0, 7.0, 1.8, 1.7),
        ("Egor Demin", "PG", 28.0, 0.190, 12.0, 4.5, 5.0, 1.6),
        ("Terrence Mann", "SG", 25.0, 0.160, 10.0, 3.8, 2.5, 1.0),
        ("Ziaire Williams", "SF", 24.0, 0.150, 9.5, 3.8, 2.0, 1.4),
        ("Day'Ron Sharpe", "C", 20.0, 0.150, 8.0, 7.5, 1.2, 0.0),
        ("Ben Saraf", "PG", 18.0, 0.130, 7.0, 2.5, 3.2, 0.9),
    ],
    "IND": [
        ("Tyrese Haliburton", "PG", 33.0, 0.280, 20.0, 3.8, 10.5, 2.8),
        ("Pascal Siakam", "PF", 34.0, 0.270, 21.5, 7.0, 3.5, 1.0),
        ("Ivica Zubac", "C", 30.0, 0.210, 15.0, 10.5, 2.0, 0.0),
        ("Andrew Nembhard", "PG", 30.0, 0.200, 12.5, 3.8, 5.0, 1.4),
        ("Aaron Nesmith", "SF", 27.0, 0.170, 11.0, 4.5, 1.8, 1.8),
        ("Obi Toppin", "PF", 24.0, 0.170, 11.5, 4.5, 1.5, 1.2),
        ("T.J. McConnell", "PG", 20.0, 0.150, 8.5, 2.8, 4.8, 0.3),
    ],
    "PHI": [
        ("Tyrese Maxey", "PG", 37.0, 0.330, 28.5, 4.0, 7.0, 3.0),
        ("LeBron James", "SF", 33.0, 0.290, 23.0, 7.5, 8.0, 2.2),
        ("Joel Embiid", "C", 30.0, 0.300, 25.5, 9.5, 4.2, 1.0),
        ("Paul George", "SF", 28.0, 0.220, 15.5, 5.0, 3.8, 2.2),
        ("VJ Edgecombe", "SG", 30.0, 0.210, 15.0, 4.5, 3.5, 1.6),
        ("Jared McCain", "PG", 22.0, 0.180, 11.0, 3.5, 3.0, 1.6),
        ("Dominick Barlow", "PF", 18.0, 0.120, 6.5, 4.5, 1.2, 0.3),
    ],
    "ORL": [
        ("Paolo Banchero", "PF", 35.5, 0.320, 27.0, 8.0, 5.0, 1.4),
        ("Franz Wagner", "SF", 35.0, 0.280, 23.5, 6.0, 5.0, 1.8),
        ("Desmond Bane", "SG", 33.0, 0.240, 18.5, 5.0, 4.5, 2.8),
        ("Jalen Suggs", "PG", 30.0, 0.190, 13.5, 4.0, 3.8, 1.9),
        ("Wendell Carter Jr.", "C", 27.0, 0.160, 10.5, 7.5, 1.8, 0.4),
        ("Tristan da Silva", "SF", 25.0, 0.150, 9.5, 3.5, 2.2, 1.2),
        ("Anthony Black", "PG", 22.0, 0.150, 9.0, 3.5, 3.5, 0.9),
    ],
    "MIA": [
        ("Giannis Antetokounmpo", "PF", 36.0, 0.350, 31.0, 11.8, 6.4, 0.7),
        ("Bam Adebayo", "C", 34.0, 0.270, 18.5, 10.0, 4.2, 0.5),
        ("Andrew Wiggins", "SF", 28.0, 0.210, 14.0, 4.8, 2.2, 1.1),
        ("Norman Powell", "SG", 30.0, 0.220, 15.5, 3.5, 2.2, 2.2),
        ("Nikola Jovic", "SF", 26.0, 0.170, 10.5, 4.0, 2.8, 1.2),
        ("Davion Mitchell", "PG", 26.0, 0.150, 8.5, 2.5, 4.5, 0.7),
        ("Pelle Larsson", "SG", 25.0, 0.150, 9.0, 3.5, 2.5, 0.9),
    ],
    "DET": [
        ("Cade Cunningham", "PG", 36.5, 0.335, 27.5, 6.5, 9.4, 2.6),
        ("Jalen Duren", "C", 30.0, 0.190, 14.5, 10.5, 2.5, 0.0),
        ("Jaden Ivey", "SG", 30.0, 0.220, 17.5, 4.0, 4.0, 1.6),
        ("Ausar Thompson", "SF", 28.0, 0.170, 11.0, 5.5, 2.8, 0.9),
        ("Tobias Harris", "PF", 28.0, 0.180, 12.5, 5.5, 2.2, 1.0),
        ("Ron Holland II", "SF", 24.0, 0.160, 10.5, 4.0, 2.0, 0.8),
        ("Marcus Sasser", "PG", 18.0, 0.130, 7.0, 2.0, 3.0, 0.9),
    ],
    "CHI": [
        ("Josh Giddey", "PG", 34.0, 0.270, 16.5, 8.5, 7.5, 1.4),
        ("Coby White", "SG", 32.0, 0.240, 19.5, 3.8, 4.5, 2.6),
        ("Matas Buzelis", "PF", 31.0, 0.230, 17.5, 6.5, 2.5, 1.9),
        ("Nikola Vucevic", "C", 29.0, 0.220, 16.0, 9.5, 3.2, 1.2),
        ("Ayo Dosunmu", "SG", 26.0, 0.180, 11.5, 4.0, 3.0, 1.2),
        ("Isaac Okoro", "SF", 24.0, 0.140, 8.5, 3.5, 1.5, 0.9),
        ("Noa Essengue", "SF", 19.0, 0.140, 8.0, 3.5, 1.0, 0.6),
    ],
    "SAS": [
        ("Victor Wembanyama", "C", 33.0, 0.330, 27.5, 12.5, 4.2, 3.2),
        ("De'Aaron Fox", "PG", 32.0, 0.280, 24.0, 4.5, 6.5, 1.6),
        ("Stephon Castle", "PG", 32.0, 0.260, 18.5, 5.0, 6.5, 1.6),
        ("Dylan Harper", "SG", 28.0, 0.220, 15.5, 4.0, 4.5, 1.2),
        ("Devin Vassell", "SG", 27.0, 0.200, 14.5, 3.8, 2.5, 2.0),
        ("Harrison Barnes", "PF", 24.0, 0.150, 9.0, 3.8, 1.5, 1.2),
        ("Luke Kornet", "C", 18.0, 0.130, 6.5, 5.5, 1.5, 0.0),
    ],
    "HOU": [
        ("Kevin Durant", "SF", 34.0, 0.320, 26.5, 6.0, 4.2, 2.0),
        ("Alperen Sengun", "C", 33.0, 0.280, 21.5, 9.8, 5.2, 0.4),
        ("Amen Thompson", "SG", 32.0, 0.230, 16.5, 8.0, 4.5, 0.9),
        ("Fred VanVleet", "PG", 32.0, 0.230, 15.0, 3.5, 6.0, 2.6),
        ("Jabari Smith Jr.", "PF", 28.0, 0.180, 12.5, 7.0, 1.5, 1.2),
        ("Tari Eason", "SF", 24.0, 0.160, 11.0, 6.0, 1.5, 0.8),
        ("Steven Adams", "C", 16.0, 0.120, 5.5, 6.5, 1.0, 0.0),
    ],
    "MEM": [
        ("Ja Morant", "PG", 33.0, 0.300, 24.0, 4.5, 8.5, 1.2),
        ("Jaren Jackson Jr.", "PF", 32.0, 0.260, 21.5, 6.5, 2.2, 1.6),
        ("Jaylen Wells", "SG", 31.0, 0.190, 13.0, 4.0, 2.5, 1.8),
        ("Zach Edey", "C", 24.0, 0.170, 10.5, 8.5, 1.2, 0.0),
        ("Ty Jerome", "PG", 24.0, 0.180, 11.0, 2.8, 3.8, 1.6),
        ("Cedric Coward", "SF", 22.0, 0.150, 9.0, 4.0, 1.8, 1.2),
        ("Brandon Clarke", "PF", 18.0, 0.130, 7.0, 5.0, 1.0, 0.0),
    ],
    "NOP": [
        ("Zion Williamson", "PF", 32.0, 0.310, 24.5, 7.0, 5.0, 0.4),
        ("Trey Murphy III", "SF", 34.0, 0.260, 21.0, 5.5, 3.5, 2.8),
        ("Jordan Poole", "SG", 28.0, 0.220, 15.0, 3.0, 3.8, 2.2),
        ("Herb Jones", "SF", 30.0, 0.180, 11.5, 4.5, 3.0, 0.9),
        ("Derik Queen", "C", 27.0, 0.210, 14.0, 8.0, 3.0, 0.6),
        ("Jeremiah Fears", "PG", 24.0, 0.180, 11.5, 3.0, 4.0, 1.0),
        ("Kevon Looney", "C", 18.0, 0.120, 5.0, 6.0, 1.0, 0.0),
    ],
    "UTA": [
        ("Lauri Markkanen", "PF", 33.0, 0.300, 26.0, 6.5, 2.0, 2.8),
        ("Ace Bailey", "SF", 30.0, 0.220, 16.5, 6.0, 2.0, 1.4),
        ("Keyonte George", "PG", 30.0, 0.230, 16.0, 3.5, 5.5, 2.0),
        ("Kyle Filipowski", "C", 26.0, 0.180, 12.0, 8.0, 2.2, 0.5),
        ("Isaiah Collier", "PG", 24.0, 0.170, 10.5, 3.0, 6.0, 0.4),
        ("Cody Williams", "SF", 24.0, 0.150, 9.0, 3.5, 2.0, 0.8),
        ("Svi Mykhailiuk", "SF", 20.0, 0.140, 8.5, 2.5, 2.0, 1.8),
    ],
    "SAC": [
        ("Domantas Sabonis", "C", 34.0, 0.290, 20.5, 13.5, 6.2, 0.6),
        ("Zach LaVine", "SG", 33.0, 0.280, 22.0, 4.5, 4.5, 2.4),
        ("DeMar DeRozan", "SF", 31.0, 0.250, 19.0, 3.8, 4.0, 0.9),
        ("Keegan Murray", "PF", 31.0, 0.190, 13.5, 6.0, 2.2, 1.9),
        ("Russell Westbrook", "PG", 24.0, 0.200, 13.0, 4.5, 6.0, 0.9),
        ("Keon Ellis", "SG", 22.0, 0.140, 8.0, 2.8, 1.5, 1.1),
        ("Maxime Raynaud", "C", 18.0, 0.130, 7.5, 5.5, 1.2, 0.5),
    ],
    "GSW": [
        ("Stephen Curry", "PG", 34.0, 0.320, 26.5, 4.5, 6.0, 4.2),
        ("Jimmy Butler", "SF", 32.0, 0.250, 18.5, 5.8, 5.0, 0.8),
        ("Draymond Green", "PF", 30.0, 0.180, 9.5, 6.5, 5.5, 1.2),
        ("Brandin Podziemski", "SG", 29.0, 0.190, 12.0, 5.0, 4.0, 2.0),
        ("Moses Moody", "SG", 27.0, 0.170, 11.5, 3.5, 1.8, 1.8),
        ("Quinten Post", "C", 20.0, 0.150, 9.0, 5.5, 1.5, 1.4),
        ("Al Horford", "C", 24.0, 0.160, 8.0, 6.0, 2.5, 1.4),
    ],
    "LAC": [
        ("Kawhi Leonard", "SF", 32.0, 0.300, 23.5, 6.0, 4.0, 2.0),
        ("James Harden", "PG", 34.0, 0.290, 22.5, 5.5, 8.5, 2.8),
        ("John Collins", "PF", 28.0, 0.200, 14.5, 7.0, 2.0, 1.2),
        ("Kris Dunn", "PG", 24.0, 0.150, 8.5, 3.5, 4.5, 0.8),
        ("Brook Lopez", "C", 20.0, 0.140, 7.5, 4.5, 1.2, 1.0),
        ("Derrick Jones Jr.", "SF", 24.0, 0.150, 9.5, 3.5, 1.2, 0.7),
        ("Nicolas Batum", "SF", 16.0, 0.110, 5.0, 3.0, 1.8, 1.0),
    ],
    "PHX": [
        ("Devin Booker", "PG", 36.0, 0.330, 27.5, 4.5, 7.0, 2.4),
        ("Jalen Green", "SG", 32.0, 0.250, 19.5, 4.5, 3.0, 2.4),
        ("Mark Williams", "C", 26.0, 0.180, 13.5, 9.0, 1.2, 0.0),
        ("Grayson Allen", "SG", 28.0, 0.190, 12.5, 3.8, 3.0, 2.2),
        ("Ryan Dunn", "SF", 24.0, 0.150, 9.0, 4.5, 1.5, 0.9),
        ("Collin Gillespie", "PG", 24.0, 0.160, 10.0, 3.0, 4.0, 1.6),
        ("Khaman Maluach", "C", 18.0, 0.140, 8.0, 6.5, 1.0, 0.4),
    ],
    "LAL": [
        ("Luka Doncic", "PG", 37.0, 0.350, 31.5, 8.6, 8.9, 3.4),
        ("Austin Reaves", "SG", 35.0, 0.270, 21.5, 4.5, 5.8, 2.2),
        ("Quentin Grimes", "SG", 31.0, 0.220, 15.5, 4.5, 3.0, 2.2),
        ("Walker Kessler", "C", 30.0, 0.200, 12.5, 11.0, 1.5, 0.0),
        ("Collin Sexton", "PG", 26.0, 0.190, 12.5, 2.8, 3.8, 1.4),
        ("Jake LaRavia", "PF", 26.0, 0.160, 9.5, 4.5, 2.5, 1.2),
        ("Sandro Mamukelashvili", "PF", 20.0, 0.150, 8.5, 5.0, 2.0, 0.9),
    ],
}

SD_SCALE = {"pts": 0.24, "reb": 0.26, "ast": 0.34, "fg3m": 0.40}
SD_MIN = {"pts": 1.5, "reb": 0.9, "ast": 0.7, "fg3m": 0.5}


def slug(name):
    s = re.sub(r"[^a-z0-9-]", "", name.lower().replace(" ", "-").replace(".", "").replace("'", ""))
    return re.sub(r"-+", "-", s).strip("-")


def r1(x):
    return round(x + 1e-9, 1)


def tip_utc(date, et_time):
    h, m = map(int, et_time.split(":"))
    dt = datetime.strptime(date, "%Y-%m-%d").replace(hour=h, minute=m, tzinfo=ET)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def et_date(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(ET).strftime("%Y-%m-%d")


def build_night(date, games, seed):
    rng = random.Random(seed)
    rows, games_out = [], []
    for away, home, tip, venue in games:
        gid = f"nba-{date.replace('-', '')}-{away}-{home}"
        games_out.append({
            "game_id": gid, "gameday": date, "gametime": tip, "gametime_et": tip,
            "tipoff_utc": tip_utc(date, tip), "away_team": away, "home_team": home,
            "venue": venue, "_fixture": True,
        })
        for team, opp, is_home in ((home, away, 1), (away, home, 0)):
            for (name, pos, minutes, usage, pts, reb, ast, fg3, *rest) in ROSTERS[team]:
                status = rest[0] if rest else "ACTIVE"
                pid = f"fx-nba-{slug(name)}"
                row = {
                    "player_id": pid, "player_display_name": name,
                    "position": pos, "team": team, "opponent_team": opp,
                    "game_id": gid, "is_home": is_home, "status": status,
                    "minutes": minutes, "usage_rate": round(usage, 3), "_fixture": True,
                }
                mu = {"pts": pts, "reb": reb, "ast": ast, "fg3m": fg3}
                fair = {}
                for key in ("pts", "reb", "ast", "fg3m"):
                    m = r1(mu[key])
                    sd = max(SD_MIN[key], r1(m * SD_SCALE[key]))
                    f = r1(m - rng.uniform(0.1, 0.4))
                    row[f"proj_{key}"] = m
                    row[f"mu_{key}"] = m
                    row[f"fair_line_{key}"] = f
                    row[f"sd_{key}"] = sd
                    fair[key] = f
                row["proj_pra"] = r1(row["proj_pts"] + row["proj_reb"] + row["proj_ast"])
                row["mu_pra"] = r1(row["mu_pts"] + row["mu_reb"] + row["mu_ast"])
                row["fair_line_pra"] = r1(fair["pts"] + fair["reb"] + fair["ast"])
                row["sd_pra"] = round(math.sqrt(row["sd_pts"] ** 2 + row["sd_reb"] ** 2 + row["sd_ast"] ** 2), 2)
                rows.append(row)
    # The Oct 22 night keeps the deliberate incomplete-input probe row.
    if date == "2026-10-22":
        rows.append({
            "player_id": "fx-nba-two_way_callup", "player_display_name": "Two-Way Callup",
            "position": "SG", "team": "NYK", "opponent_team": "BOS",
            "game_id": "nba-20261022-BOS-NYK", "is_home": 1, "status": "ACTIVE",
            "minutes": 9.0, "usage_rate": 0.14, "_fixture": True,
            "proj_pts": None, "fair_line_pts": None, "mu_pts": None, "sd_pts": None,
            "proj_reb": 1.8, "fair_line_reb": 1.5, "mu_reb": 1.8, "sd_reb": 0.9,
            "proj_ast": 1.2, "fair_line_ast": 1.5, "mu_ast": 1.2, "sd_ast": 0.7,
            "proj_fg3m": 0.4, "fair_line_fg3m": 0.5, "mu_fg3m": 0.4, "sd_fg3m": 0.5,
            "proj_pra": None, "fair_line_pra": None, "mu_pra": None, "sd_pra": None,
        })
    return rows, games_out


def p_over(mu, sd, line):
    if not sd > 0:
        return 0.5
    return 1.0 - ND.cdf((line + 0.5 - mu) / sd)


def american(p):
    """Deterministic book price from a priced probability (4.5% overround pair)."""
    p = min(0.90, max(0.10, p))
    if p >= 0.5:
        odds = -int(round((p / (1 - p)) * 100 / 5.0) * 5)
        return max(min(odds, -105), -500)
    odds = int(round(((1 - p) / p) * 100 / 5.0) * 5)
    return min(max(odds, 100), 500)


def build_odds(rows, date, stamp, seed):
    rng = random.Random(seed)
    by_game = {}
    for r in rows:
        by_game.setdefault(r["game_id"], []).append(r)
    quotes, n = [], 0
    for gid in sorted(by_game):
        players = sorted(by_game[gid], key=lambda r: (-r["usage_rate"], r["player_id"]))
        combos = [
            (players[0], "points"), (players[0], "pra"), (players[1], "points"),
            (players[2], "assists"), (players[3], "rebounds"), (players[1], "threes"),
            (players[5], "rebounds"), (players[2], "points"),
        ]
        for player, market in combos[: rng.choice([5, 6, 6])]:
            suffix = {"points": "pts", "rebounds": "reb", "assists": "ast", "threes": "fg3m", "pra": "pra"}[market]
            mu, sd = player[f"mu_{suffix}"], player[f"sd_{suffix}"]
            fair = player[f"fair_line_{suffix}"]
            base = math.floor(fair) + 0.5
            line = None
            # Low-mean discrete markets (3PM, low assists) need a wider rung
            # search to land near the model median — otherwise the price
            # conversion degenerates into ±1500 absurdities.
            for window in (0.12, 0.18):
                best = None
                for delta in (0.0, -0.5, 0.5, -1.0, 1.0, -1.5, 1.5, -2.0, 2.0):
                    cand = max(0.5, round(base + delta, 1))
                    edge = abs(p_over(mu, sd, cand) - 0.5)
                    if edge <= window and (best is None or edge < best[1]):
                        best = (cand, edge)
                    if best and best[1] <= 0.06:
                        break
                if best:
                    line = best[0]
                    break
            if line is None:
                line = max(0.5, round(base, 1))
            p = p_over(mu, sd, line)
            best_side = "OVER" if p >= 0.5 else "UNDER"
            p_win = p if best_side == "OVER" else 1.0 - p
            # Realistic two-sided prices: the model side gets a small hold,
            # the opposite side a hair of value (deterministic).
            over_odds = american(p + 0.0225)
            under_odds = american((1 - p) + 0.0225)
            payout = abs((over_odds if best_side == "OVER" else under_odds) / 100.0)
            payout = payout if (over_odds if best_side == "OVER" else under_odds) < 0 else payout
            price = over_odds if best_side == "OVER" else under_odds
            dec = (abs(price) / 100.0) if price < 0 else (price / 100.0)
            expected = round(p_win * dec - (1 - p_win), 3)
            quotes.append({
                "quote_id": f"fixture_{n:02d}_{player['player_id']}_{market}",
                "provider_quote_id": f"fixture_{n:02d}_{player['player_id']}_{market}",
                "source_url": f"propwire://fixture/nba/{date}",
                "book": "PropWire Fixture",
                "player_id": player["player_id"],
                "player_name": player["player_display_name"],
                "team": player["team"], "opponent": player["opponent_team"],
                "game_id": player["game_id"], "position": player["position"],
                "market": market, "line": line, "fair_line": fair,
                "over_odds": over_odds, "under_odds": under_odds,
                "observed_at": stamp,
                "source": SYNTH_SOURCE,
                "verified": False, "_fixture": True,
                "unit": {"points": "pts", "rebounds": "reb", "assists": "ast", "threes": "3pm", "pra": "pra"}[market],
                "evaluation": {
                    "is_qualified": False, "status": "UNVERIFIED", "best_side": best_side,
                    "prob_edge": round(abs(p - 0.5), 3),
                    "break_even_adv": round(abs(p - 0.5) - 0.03, 3),
                    "expected_return": expected,
                    "actionable_stake": 0.0, "catalyst": "none",
                    "injury_context": "none (fixture)",
                },
            })
            n += 1
    return {
        "schema_version": "nba.v1", "feed_status": "fixture", "_fixture": True,
        "fixture_notice": NOTICE, "updated_at": stamp, "slate": date,
        "verified_books_count": 0, "verified_quotes_count": 0,
        "monitored_books": [], "unverified_books": ["PropWire Fixture"],
        "total_quotes": len(quotes), "qualified_count": 0, "quotes": quotes,
    }


def beneficiary_entry(player, injury, share, minutes, role, risk):
    return {
        "_fixture": True,
        "player_id": player["player_id"], "player_name": player["player_display_name"],
        "team": player["team"], "opponent": player["opponent_team"],
        "game_id": player["game_id"], "position": player["position"],
        "catalyst_injury": f"{injury['player_name']} ({injury['injury_type']} {injury['report_status']})",
        "injury_id": injury["injury_id"], "role_type": role,
        "role_label": "PROVISIONAL SURGE (Minutes Vacancy)", "role_class": "role-surge",
        "absorption_share": share, "added_minutes": minutes,
        "invalidation_risk": risk,
    }


def make_injuries(rows, date, plan, stamp):
    by_id = {r["player_id"]: r for r in rows}
    injuries, beneficiaries = [], {}
    for i, (out_id, status, itype, practice, severity, source, notes, benes) in enumerate(plan):
        out_player = by_id[out_id]
        weight = 0.5 if status == "QUESTIONABLE" else 1.0
        inj = {
            "_fixture": True,
            "injury_id": f"fx-inj-{i + 1}-{date}",
            "player_id": out_id, "player_name": out_player["player_display_name"],
            "team": out_player["team"], "opponent": out_player["opponent_team"],
            "game_id": out_player["game_id"], "position": out_player["position"],
            "injury_type": itype, "report_status": status, "practice_status": practice,
            "severity": severity, "source": source, "updated_at": stamp, "notes": notes,
            "vacated_minutes": r1(out_player["minutes"] * weight),
            "vacated_usage": out_player["usage_rate"],
            "redistribution_plan": {},
        }
        for (bene_id, share, minutes, role, risk) in benes:
            bene = by_id[bene_id]
            inj["redistribution_plan"][bene_id] = {
                "_fixture": True,
                "beneficiary_name": bene["player_display_name"], "position": bene["position"],
                "absorption_share": share, "role_type": role, "added_minutes": minutes,
                "role_label": "PROVISIONAL SURGE (Minutes Vacancy)", "role_class": "role-surge",
                "invalidation_risk": risk,
            }
            beneficiaries[bene_id] = beneficiary_entry(bene, inj, share, minutes, role, risk)
        injuries.append(inj)
    return {
        "_fixture": True, "as_of": stamp, "slate_date": date, "season": 2026,
        "total_active_injuries": len(injuries),
        "injuries": injuries, "impacted_beneficiaries": beneficiaries,
    }


def oct22_injuries(rows):
    by_id = {r["player_id"]: r for r in rows}
    bos = sorted([r for r in rows if r["team"] == "BOS"], key=lambda r: (-r["usage_rate"], r["player_id"]))
    plan = [
        # REAL public status (verified Oct 2026 reporting): Tatum continues his
        # Achilles rehab and has no return timetable. Stat impact is synthetic.
        ("fx-nba-jayson-tatum", "OUT", "Achilles (left) — rehab", "Out (Rehab Assignment)", "CRITICAL",
         "Public injury reporting (real status on a fixture slate); stat impact modeled synthetically.",
         "Continues his Achilles rehab with no return timetable — real public reporting; the slate modeling here is synthetic. Boston redistributes his creation load in the meantime.",
         [(bos[0]["player_id"], 0.40, 6.0, "Primary creation minutes",
           "Defensive shells bracket his spots once the scouting report catches up."),
          (bos[1]["player_id"], 0.30, 4.5, "Secondary on-ball bulk",
           "Bench units may route creation through the backup guard instead.")]),
        # Operational availability (not an injury): two-way shuttle.
        ("fx-nba-two_way_callup", "QUESTIONABLE", "Two-Way Assignment (G League Shuttle)", "Availability Pending", "ELEVATED",
         "Operational availability context (fixture) — not an injury report.",
         "Two-way shuttle: whether he suits up depends on the G League assignment window on a synthetic fixture slate.",
         []),
    ]
    return make_injuries(rows, "2026-10-22", plan, "2026-10-22T17:00:00Z")


def oct23_injuries(rows):
    by_id = {r["player_id"]: r for r in rows}
    mia = sorted([r for r in rows if r["team"] == "MIA"], key=lambda r: (-r["usage_rate"], r["player_id"]))
    mem = sorted([r for r in rows if r["team"] == "MEM"], key=lambda r: (-r["usage_rate"], r["player_id"]))
    phx = sorted([r for r in rows if r["team"] == "PHX"], key=lambda r: (-r["usage_rate"], r["player_id"]))
    plan = [
        (mia[3]["player_id"], "QUESTIONABLE", "Ankle Sprain (Grade 1)", "Limited Practice (Estimated)", "ELEVATED",
         INJ_SOURCE,
         "Hypothetical fixture status (not a real injury report): game-time decision with a limited practice week; minutes risk flagged without removing the player from the board.",
         [(mia[4]["player_id"], 0.35, 5.5, "Wing scoring bulk", "Bench units may route creation through the backup guard instead."),
          (mia[5]["player_id"], 0.25, 3.5, "Second-unit guard minutes", "Frontcourt foul trouble reshuffles the rotation within a quarter.")]),
        (mem[3]["player_id"], "OUT", "Calf Strain", "Did Not Practice (Estimated)", "CRITICAL",
         INJ_SOURCE,
         "Hypothetical fixture status (not a real injury report): vacates the backup-center minutes; redistribution is conditional on the actual inactive list.",
         [(mem[6]["player_id"], 0.40, 4.5, "Second-unit forward minutes", "Frontcourt foul trouble reshuffles the rotation within a quarter."),
          (mem[5]["player_id"], 0.30, 3.5, "Bench wing forward spot", "Small-ball looks could bypass the traditional backup entirely.")]),
        (phx[3]["player_id"], "QUESTIONABLE", "Illness (Non-COVID)", "Limited Practice (Estimated)", "ELEVATED",
         INJ_SOURCE,
         "Hypothetical fixture status (not a real injury report): illness limits practice availability; a game-time decision on a synthetic fixture slate.",
         [(phx[5]["player_id"], 0.35, 4.0, "Backup guard minutes", "Blowout risk truncates the fourth-quarter window the expanded role depends on."),
          (phx[4]["player_id"], 0.30, 3.0, "Wing scoring bulk", "Defensive matchups dictate whether the expanded role survives the second unit.")]),
    ]
    return make_injuries(rows, "2026-10-23", plan, "2026-10-23T17:00:00Z")


def oct29_injuries(rows):
    by_id = {r["player_id"]: r for r in rows}
    bos = sorted([r for r in rows if r["team"] == "BOS"], key=lambda r: (-r["usage_rate"], r["player_id"]))
    lal = sorted([r for r in rows if r["team"] == "LAL"], key=lambda r: (-r["usage_rate"], r["player_id"]))
    gsw = sorted([r for r in rows if r["team"] == "GSW"], key=lambda r: (-r["usage_rate"], r["player_id"]))
    plan = [
        ("fx-nba-jayson-tatum", "OUT", "Achilles (left) — rehab", "Out (Rehab Assignment)", "CRITICAL",
         "Public injury reporting (real status on a fixture slate); stat impact modeled synthetically.",
         "Continues his Achilles rehab with no return timetable — real public reporting; the slate modeling here is synthetic. Boston redistributes his creation load in the meantime.",
         [(bos[0]["player_id"], 0.40, 6.0, "Primary creation minutes",
           "Defensive shells bracket his spots once the scouting report catches up."),
          (bos[1]["player_id"], 0.30, 4.5, "Secondary on-ball bulk",
           "Bench units may route creation through the backup guard instead.")]),
        (lal[3]["player_id"], "QUESTIONABLE", "Ankle Sprain (Grade 1)", "Limited Practice (Estimated)", "ELEVATED",
         INJ_SOURCE,
         "Hypothetical fixture status (not a real injury report): game-time decision with a limited practice week; minutes risk flagged without removing the player from the board.",
         [(lal[4]["player_id"], 0.35, 5.0, "Wing scoring bulk", "Bench units may route creation through the backup guard instead."),
          (lal[5]["player_id"], 0.25, 3.5, "Second-unit guard minutes", "Frontcourt foul trouble reshuffles the rotation within a quarter.")]),
        (gsw[3]["player_id"], "QUESTIONABLE", "Knee Soreness", "Day-to-Day", "ELEVATED",
         INJ_SOURCE,
         "Hypothetical fixture status (not a real injury report): knee soreness limits scrimmage time; day-to-day designation monitored ahead of tip-off.",
         [(gsw[4]["player_id"], 0.35, 4.5, "Secondary scoring role", "Rotation dependent on match matchups."),
          (gsw[5]["player_id"], 0.30, 3.0, "Wing defense minutes", "Small-ball looks alter wing minutes.")]),
    ]
    return make_injuries(rows, "2026-10-29", plan, "2026-10-29T17:00:00Z")


def validate(nights):
    for date, (rows, games, env, inj) in nights.items():
        ids = set()
        for r in rows:
            assert r["_fixture"] is True, r["player_id"]
            for f in ("player_id", "player_display_name", "team", "opponent_team", "game_id", "position"):
                assert r.get(f) is not None, (r["player_id"], f)
            for suf in ("pts", "reb", "ast", "fg3m", "pra"):
                for pre in ("proj_", "fair_line_", "mu_", "sd_"):
                    v = r[f"{pre}{suf}"]
                    assert v is None or isinstance(v, (int, float)), (r["player_id"], pre + suf)
            if all(isinstance(r.get(f"mu_{s}"), (int, float)) for s in ("pts", "reb", "ast")):
                assert abs(r["mu_pra"] - (r["mu_pts"] + r["mu_reb"] + r["mu_ast"])) < 0.06, r["player_id"]
                assert abs(r["sd_pra"] - math.sqrt(r["sd_pts"] ** 2 + r["sd_reb"] ** 2 + r["sd_ast"] ** 2)) < 0.06, r["player_id"]
            ids.add(r["player_id"])
        assert len(ids) == len(rows)
        gids = set()
        for g in games:
            assert g["_fixture"] is True and re.match(r"^nba-\d{8}-[A-Z]{2,4}-[A-Z]{2,4}$", g["game_id"])
            assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", g["tipoff_utc"])
            assert re.match(r"^\d{2}:\d{2}$", g["gametime_et"])
            assert et_date(g["tipoff_utc"]) == date, g["game_id"]
            gids.add(g["game_id"])
        for r in rows:
            assert r["game_id"] in gids, r["player_id"]
        assert env["feed_status"] == "fixture" and env["_fixture"] is True and env["slate"] == date
        assert env["total_quotes"] == len(env["quotes"]) and len(env["quotes"]) >= 10
        qids = set()
        for q in env["quotes"]:
            assert q["_fixture"] is True and q["verified"] is False
            assert re.search(r"not a sportsbook quote", q["source"], re.I)
            assert q["market"] in MARKETS and q["line"] is not None and q["fair_line"] is not None
            assert isinstance(q["evaluation"]["prob_edge"], (int, float)) and isinstance(q["evaluation"]["expected_return"], (int, float))
            assert q["player_id"] in ids, q["quote_id"]
            row = next(r for r in rows if r["player_id"] == q["player_id"])
            assert q["game_id"] == row["game_id"], q["quote_id"]
            assert q["over_odds"] <= -105 or q["over_odds"] >= 100, q["quote_id"]
            qids.add(q["quote_id"])
        assert len(qids) == len(env["quotes"])
        assert inj["_fixture"] is True and inj["slate_date"] == date
        assert inj["total_active_injuries"] == len(inj["injuries"]) >= 1
        for item in inj["injuries"]:
            assert item["_fixture"] is True and item["player_id"] in ids, item["player_id"]
            assert item["report_status"] in ("OUT", "QUESTIONABLE", "LIMITED", "DAY-TO-DAY")
            assert isinstance(item["vacated_minutes"], (int, float))
            for bene in item["redistribution_plan"].values():
                assert bene["_fixture"] is True and bene["added_minutes"] > 0
        for pid, bene in inj["impacted_beneficiaries"].items():
            assert bene["_fixture"] is True and pid in ids and bene["player_id"] == pid
            assert bene["added_minutes"] > 0
    print("validate: OK")


if __name__ == "__main__":
    rows22, games22 = build_night("2026-10-22", OCT22_GAMES, 20261022)
    rows23, games23 = build_night("2026-10-23", OCT23_GAMES, 20261023)
    rows29, games29 = build_night("2026-10-29", OCT29_GAMES, 20261029)
    odds22 = build_odds(rows22, "2026-10-22", "2026-10-22T17:00:00Z", 20261222)
    odds23 = build_odds(rows23, "2026-10-23", "2026-10-23T17:00:00Z", 20261223)
    odds29 = build_odds(rows29, "2026-10-29", "2026-10-29T17:00:00Z", 20261229)
    inj22 = oct22_injuries(rows22)
    inj23 = oct23_injuries(rows23)
    inj29 = oct29_injuries(rows29)
    nights = {
        "2026-10-22": (rows22, games22, odds22, inj22),
        "2026-10-23": (rows23, games23, odds23, inj23),
        "2026-10-29": (rows29, games29, odds29, inj29),
    }
    validate(nights)
    outputs = {}
    for date, (rws, gms, env, inj) in nights.items():
        outputs[f"nba_slate_{date}.json"] = rws
        outputs[f"nba_games_{date}.json"] = gms
        outputs[f"nba_odds_{date}.json"] = env
        outputs[f"nba_injuries_{date}.json"] = inj
    for name, payload in outputs.items():
        with open(os.path.join(VIEWER, name), "w") as f:
            json.dump(payload, f, indent=1)
            f.write("\n")
        print(f"wrote {name}")
    for date, (rws, gms, env, inj) in nights.items():
        print(f"{date}: {len(gms)} games, {len(rws)} rows, {len(env['quotes'])} quotes, {inj['total_active_injuries']} injuries")

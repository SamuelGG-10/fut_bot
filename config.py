import os

TELEGRAM_TOKEN     = os.environ.get("TELEGRAM_TOKEN", "8603220738:AAHr5MOwEnuAoLReyf4csYTrwQfGzmZ_aLM")
FOOTBALL_API_TOKEN = os.environ.get("FOOTBALL_API_TOKEN", "796def20f1f74a319f29d0e48d1955b9")
ODDS_API_TOKEN     = os.environ.get("ODDS_API_TOKEN", "f31d30b339c3424bb93daefdfa3b430c")

LIGAS = {
    "Premier League": "PL",
    "La Liga":        "PD",
    "Bundesliga":     "BL1",
    "Serie A":        "SA",
    "Champions":      "CL",
}

ODDS_LIGAS = {
    "PL":  "soccer_england_premier_league",
    "PD":  "soccer_spain_la_liga",
    "BL1": "soccer_germany_bundesliga",
    "SA":  "soccer_italy_serie_a",
    "CL":  "soccer_uefa_champions_league",
}

UMBRAL_BTTS     = 65
UMBRAL_OVER25   = 60
UMBRAL_PARTIDOS = 10
VENTAJA_MODELO  = 5
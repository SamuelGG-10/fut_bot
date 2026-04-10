import requests
from datetime import datetime, timedelta
from config import FOOTBALL_API_TOKEN, ODDS_API_TOKEN, ODDS_LIGAS

BASE_URL   = "https://api.football-data.org/v4"
HEADERS    = {"X-Auth-Token": FOOTBALL_API_TOKEN}
ODDS_URL   = "https://api.the-odds-api.com/v4"


# ── football-data.org ────────────────────────────────────────

def get(endpoint, params=None):
    r = requests.get(f"{BASE_URL}/{endpoint}", headers=HEADERS, params=params)
    r.raise_for_status()
    return r.json()


def partidos_hoy():
    return get("matches").get("matches", [])


def detalle_partido(match_id):
    """Trae corners y tarjetas — solo disponible en detalle individual."""
    return get(f"matches/{match_id}")


def ultimos_partidos(team_id, n=10):
    data = get(f"teams/{team_id}/matches", params={
        "status": "FINISHED",
        "limit": n
    })
    return data.get("matches", [])


def proximos_partidos(competition_code, dias=3):
    hoy    = datetime.utcnow().strftime("%Y-%m-%d")
    limite = (datetime.utcnow() + timedelta(days=dias)).strftime("%Y-%m-%d")
    data = get(f"competitions/{competition_code}/matches", params={
        "status":   "SCHEDULED",
        "dateFrom": hoy,
        "dateTo":   limite
    })
    return data.get("matches", [])


def partidos_equipo_detalle(team_id, n=10):
    """
    Trae los últimos N partidos con detalle completo
    (corners, tarjetas). Usa más llamadas a la API.
    """
    partidos = ultimos_partidos(team_id, n)
    detallados = []
    for p in partidos:
        try:
            d = detalle_partido(p["id"])
            detallados.append(d)
        except Exception:
            detallados.append(p)
    return detallados


# ── The Odds API ─────────────────────────────────────────────

def get_cuotas(competition_code):
    """
    Trae las cuotas 1X2 de los próximos partidos de una liga.
    Devuelve dict: {(home, away): {"home": p, "draw": p, "away": p}}
    donde p es probabilidad implícita (0-100).
    """
    sport = ODDS_LIGAS.get(competition_code)
    if not sport:
        return {}

    try:
        r = requests.get(
            f"{ODDS_URL}/sports/{sport}/odds",
            params={
                "apiKey":  ODDS_API_TOKEN,
                "regions": "eu",
                "markets": "h2h",
                "oddsFormat": "decimal"
            }
        )
        r.raise_for_status()
        eventos = r.json()
    except Exception:
        return {}

    cuotas = {}
    for ev in eventos:
        home = ev.get("home_team", "")
        away = ev.get("away_team", "")
        bookmakers = ev.get("bookmakers", [])
        if not bookmakers:
            continue

        # Promedio entre bookmakers disponibles
        probs = {"home": [], "draw": [], "away": []}
        for bm in bookmakers:
            for market in bm.get("markets", []):
                if market["key"] != "h2h":
                    continue
                for outcome in market["outcomes"]:
                    odd = outcome["price"]
                    prob = round(100 / odd, 1)
                    if outcome["name"] == home:
                        probs["home"].append(prob)
                    elif outcome["name"] == away:
                        probs["away"].append(prob)
                    else:
                        probs["draw"].append(prob)

        if probs["home"] and probs["away"]:
            cuotas[(home, away)] = {
                "home": round(sum(probs["home"]) / len(probs["home"]), 1),
                "draw": round(sum(probs["draw"]) / len(probs["draw"]), 1) if probs["draw"] else 0,
                "away": round(sum(probs["away"]) / len(probs["away"]), 1),
            }

    return cuotas
def buscar_equipo_en_liga(nombre, competition_code):
    """
    Busca un equipo por nombre dentro de una liga específica.
    Más preciso que buscar globalmente.
    """
    data = get(f"competitions/{competition_code}/teams")
    equipos = data.get("teams", [])
    nombre_lower = nombre.lower()
    
    for e in equipos:
        if (nombre_lower in e["name"].lower() or 
            nombre_lower in e.get("shortName", "").lower() or
            nombre_lower in e.get("tla", "").lower()):
            return e
    return None


def buscar_equipo_global(nombre):
    """
    Busca en todas las ligas. Acepta nombres parciales,
    acentos, abreviaciones y múltiples palabras.
    """
    from config import LIGAS
    import unicodedata

    def normalizar(texto):
        # Quita acentos y pasa a minúsculas
        texto = unicodedata.normalize("NFD", texto)
        texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
        return texto.lower().strip()

    nombre_norm = normalizar(nombre)
    palabras = nombre_norm.split()  # ["atletico", "de", "madrid"]

    mejor = None
    mejor_score = 0

    for code in LIGAS.values():
        try:
            data = get(f"competitions/{code}/teams")
            equipos = data.get("teams", [])
        except Exception:
            continue

        for e in equipos:
            candidatos = [
                normalizar(e.get("name", "")),
                normalizar(e.get("shortName", "")),
                normalizar(e.get("tla", "")),
            ]

            for c in candidatos:
                # Coincidencia exacta — máxima prioridad
                if nombre_norm == c:
                    return e

                # Cuántas palabras del nombre buscado están en el candidato
                hits = sum(1 for p in palabras if p in c)
                score = hits / len(palabras)

                # También chequea si el candidato contiene el nombre completo
                if nombre_norm in c or c in nombre_norm:
                    score = max(score, 0.9)

                if score > mejor_score:
                    mejor_score = score
                    mejor = e

    # Solo retorna si hay una coincidencia razonable (>50%)
    if mejor_score >= 0.5:
        return mejor
    return None


def cargar_historial_equipo(team_id, n=20):
    """
    Trae los últimos N partidos terminados de un equipo
    y los devuelve listos para guardar en DB.
    """
    return ultimos_partidos(team_id, n)

def partidos_recientes(dias=3):
    """
    Trae todos los partidos terminados de los últimos N días
    de todas las ligas configuradas.
    """
    from config import LIGAS
    from datetime import datetime, timedelta
    
    fecha_desde = (datetime.utcnow() - timedelta(days=dias)).strftime("%Y-%m-%d")
    fecha_hasta = datetime.utcnow().strftime("%Y-%m-%d")
    
    todos = []
    for code in LIGAS.values():
        try:
            data = get(f"competitions/{code}/matches", params={
                "status":   "FINISHED",
                "dateFrom": fecha_desde,
                "dateTo":   fecha_hasta
            })
            todos.extend(data.get("matches", []))
        except Exception as e:
            log.warning(f"Error jalando partidos de {code}: {e}")
    return todos
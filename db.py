import sqlite3

DB = "futbol.db"


def init_db():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS partidos (
            id              INTEGER PRIMARY KEY,
            competition     TEXT,
            home_id         INTEGER,
            away_id         INTEGER,
            home_name       TEXT,
            away_name       TEXT,
            fecha           TEXT,
            goles_home      INTEGER,
            goles_away      INTEGER,
            corners_home    INTEGER,
            corners_away    INTEGER,
            amarillas_home  INTEGER,
            amarillas_away  INTEGER,
            status          TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS suscriptores (
            chat_id INTEGER PRIMARY KEY,
            ligas   TEXT DEFAULT 'PL,PD,BL1,SA,CL'
        )
    """)
    con.commit()
    con.close()


def guardar_partido(p):
    """
    football-data.org solo incluye corners/tarjetas
    en el detalle de partido individual, no en listas.
    Se guardan como None si no están disponibles.
    """
    odds = p.get("odds", {})
    stats = p.get("statistics", [])

    corners_home = corners_away = None
    amarillas_home = amarillas_away = None

    for s in stats:
        if s.get("type") == "CORNERS":
            corners_home = s.get("home")
            corners_away = s.get("away")
        if s.get("type") == "YELLOW_CARDS":
            amarillas_home = s.get("home")
            amarillas_away = s.get("away")

    con = sqlite3.connect(DB)
    con.execute("""
        INSERT OR REPLACE INTO partidos
        (id, competition, home_id, away_id, home_name, away_name,
         fecha, goles_home, goles_away,
         corners_home, corners_away, amarillas_home, amarillas_away, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        p["id"],
        p["competition"]["name"],
        p["homeTeam"]["id"],
        p["awayTeam"]["id"],
        p["homeTeam"]["name"],
        p["awayTeam"]["name"],
        p["utcDate"][:10],
        p["score"]["fullTime"].get("home"),
        p["score"]["fullTime"].get("away"),
        corners_home, corners_away,
        amarillas_home, amarillas_away,
        p["status"]
    ))
    con.commit()
    con.close()


def get_partidos_equipo(team_id, n=10):
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("""
        SELECT goles_home, goles_away, home_id,
               corners_home, corners_away,
               amarillas_home, amarillas_away,
               fecha
        FROM partidos
        WHERE (home_id = ? OR away_id = ?) AND status = 'FINISHED'
        ORDER BY fecha DESC LIMIT ?
    """, (team_id, team_id, n))
    rows = cur.fetchall()
    con.close()
    return rows


def get_suscriptores():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("SELECT chat_id FROM suscriptores")
    ids = [r[0] for r in cur.fetchall()]
    con.close()
    return ids


def agregar_suscriptor(chat_id):
    con = sqlite3.connect(DB)
    con.execute("INSERT OR IGNORE INTO suscriptores (chat_id) VALUES (?)", (chat_id,))
    con.commit()
    con.close()


def eliminar_suscriptor(chat_id):
    con = sqlite3.connect(DB)
    con.execute("DELETE FROM suscriptores WHERE chat_id = ?", (chat_id,))
    con.commit()
    con.close()

def actualizar_resultado(partido_id, goles_home, goles_away, status):
    """Actualiza el resultado de un partido ya guardado."""
    con = sqlite3.connect(DB)
    con.execute("""
        UPDATE partidos
        SET goles_home = ?, goles_away = ?, status = ?
        WHERE id = ?
    """, (goles_home, goles_away, status, partido_id))
    con.commit()
    con.close()


def partido_existe(partido_id):
    """Verifica si un partido ya está en la base de datos."""
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("SELECT id FROM partidos WHERE id = ?", (partido_id,))
    existe = cur.fetchone() is not None
    con.close()
    return existe
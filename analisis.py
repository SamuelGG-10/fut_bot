from datetime import datetime
from db import get_partidos_equipo
from config import (
    UMBRAL_BTTS, UMBRAL_OVER25, UMBRAL_PARTIDOS,
    STAKE_DEFAULT, UMBRAL_PROB_BOT, UMBRAL_EDGE, UMBRAL_EV
)


# ══════════════════════════════════════════════════════════════
# 1. ESTADÍSTICAS BASE
# ══════════════════════════════════════════════════════════════

def calcular_stats(team_id, n=UMBRAL_PARTIDOS):
    filas = get_partidos_equipo(team_id, n)
    if not filas:
        return None

    btts = over15 = over25 = over35 = 0
    goles_a_favor, goles_en_contra = [], []
    corners_totales, amarillas_totales = [], []
    forma, fechas = [], []
    local_j = local_g = local_e = local_p = 0
    visit_j = visit_g = visit_e = visit_p = 0

    for fila in filas:
        gh, ga, home_id, ch, ca, yh, ya, fecha = fila
        if gh is None or ga is None:
            continue

        es_local = home_id == team_id
        gf = gh if es_local else ga
        gc = ga if es_local else gh
        total = gh + ga

        goles_a_favor.append(gf)
        goles_en_contra.append(gc)

        if gh > 0 and ga > 0:  btts   += 1
        if total > 1:           over15 += 1
        if total > 2:           over25 += 1
        if total > 3:           over35 += 1

        if ch is not None and ca is not None:
            corners_totales.append(ch + ca)
        if yh is not None and ya is not None:
            amarillas_totales.append(yh + ya)

        if gf > gc:   forma.append("W")
        elif gf == gc: forma.append("D")
        else:          forma.append("L")

        if es_local:
            local_j += 1
            if gf > gc: local_g += 1
            elif gf == gc: local_e += 1
            else: local_p += 1
        else:
            visit_j += 1
            if gf > gc: visit_g += 1
            elif gf == gc: visit_e += 1
            else: visit_p += 1

        if fecha:
            fechas.append(fecha)

    j = len(goles_a_favor)
    if j == 0:
        return None

    pesos = [2 ** i for i in range(len(forma))]
    puntos = sum(
        (3 if r == "W" else 1 if r == "D" else 0) * w
        for r, w in zip(forma, pesos)
    )
    max_pts = sum(3 * w for w in pesos)
    forma_pond = round(puntos / max_pts * 100, 1) if max_pts else 0

    descanso = None
    if fechas:
        try:
            dias = (datetime.utcnow() - datetime.strptime(max(fechas), "%Y-%m-%d")).days
            descanso = dias
        except Exception:
            pass

    return {
        "jugados":         j,
        "btts":            btts,
        "btts_pct":        round(btts / j * 100),
        "over15":          over15,
        "over15_pct":      round(over15 / j * 100),
        "over25":          over25,
        "over25_pct":      round(over25 / j * 100),
        "over35":          over35,
        "over35_pct":      round(over35 / j * 100),
        "prom_gf":         round(sum(goles_a_favor) / j, 2),
        "prom_gc":         round(sum(goles_en_contra) / j, 2),
        "prom_corners":    round(sum(corners_totales) / len(corners_totales), 1) if corners_totales else None,
        "prom_amarillas":  round(sum(amarillas_totales) / len(amarillas_totales), 1) if amarillas_totales else None,
        "forma":           forma,
        "forma_ponderada": forma_pond,
        "local":  {"j": local_j, "g": local_g, "e": local_e, "p": local_p},
        "visit":  {"j": visit_j, "g": visit_g, "e": visit_e, "p": visit_p},
        "descanso_dias":   descanso,
    }


# ══════════════════════════════════════════════════════════════
# 2. MODELO POISSON
# ══════════════════════════════════════════════════════════════

def prob_modelo(sh, sa):
    import math

    def poisson(lam, k):
        return (lam ** k) * math.exp(-lam) / math.factorial(k)

    lam_h = (sh["prom_gf"] + sa["prom_gc"]) / 2
    lam_a = (sa["prom_gf"] + sh["prom_gc"]) / 2

    p_home = p_draw = p_away = 0.0
    for i in range(8):
        for j in range(8):
            p = poisson(lam_h, i) * poisson(lam_a, j)
            if i > j:    p_home += p
            elif i == j: p_draw += p
            else:        p_away += p

    total = p_home + p_draw + p_away
    return {
        "home": round(p_home / total, 4),
        "draw": round(p_draw / total, 4),
        "away": round(p_away / total, 4),
    }


# ══════════════════════════════════════════════════════════════
# 3. MOTOR DE VALOR ESPERADO
# ══════════════════════════════════════════════════════════════

def prob_implicita(cuota: float) -> float:
    """Convierte cuota decimal a probabilidad implícita."""
    if not cuota or cuota <= 1:
        return None
    return round(1 / cuota, 4)


def calcular_edge(prob_bot: float, cuota: float):
    """Edge = prob_bot - prob_implicita."""
    pi = prob_implicita(cuota)
    if pi is None:
        return None
    return round(prob_bot - pi, 4)


def calcular_ev(prob_bot: float, cuota: float, stake: float = STAKE_DEFAULT):
    """EV = (prob_bot * ganancia) - (prob_no * stake)."""
    if not cuota or cuota <= 1:
        return None
    ganancia  = stake * (cuota - 1)
    perdida   = stake
    ev = (prob_bot * ganancia) - ((1 - prob_bot) * perdida)
    return round(ev, 2)


def evaluar_jugada(nombre: str, prob_bot: float, cuota: float,
                   stake: float = STAKE_DEFAULT):
    """
    Evalúa una jugada candidata.
    Devuelve dict con todos los cálculos o None si no cumple filtros.
    """
    if prob_bot < UMBRAL_PROB_BOT:
        return None
    if not cuota or cuota <= 1:
        # Sin cuota: mostrar igual si prob_bot es alta, sin EV
        return {
            "nombre":       nombre,
            "prob_bot":     prob_bot,
            "cuota":        None,
            "prob_imp":     None,
            "edge":         None,
            "ev":           None,
            "recomendada":  True,
            "sin_cuota":    True,
        }

    pi    = prob_implicita(cuota)
    edge  = calcular_edge(prob_bot, cuota)
    ev    = calcular_ev(prob_bot, cuota, stake)

    recomendada = (
        prob_bot >= UMBRAL_PROB_BOT and
        edge     >  UMBRAL_EDGE     and
        ev       >  UMBRAL_EV
    )

    if not recomendada:
        return None

    return {
        "nombre":      nombre,
        "prob_bot":    prob_bot,
        "cuota":       cuota,
        "prob_imp":    pi,
        "edge":        edge,
        "ev":          ev,
        "recomendada": True,
        "sin_cuota":   False,
    }


def formatear_jugada(j: dict, stake: float = STAKE_DEFAULT) -> str:
    """Formatea una jugada evaluada para Telegram."""
    if j["sin_cuota"]:
        return (
            f"📌 *Jugada:* {j['nombre']}\n"
            f"📊 *Prob. bot:* {j['prob_bot']*100:.1f}%\n"
            f"⚠️ Sin cuota disponible\n"
            f"✅ *Estado:* Candidata"
        )
    return (
        f"📌 *Jugada:* {j['nombre']}\n"
        f"📊 *Prob. bot:* {j['prob_bot']*100:.1f}%\n"
        f"💰 *Cuota casa:* {j['cuota']}\n"
        f"📉 *Prob. implícita:* {j['prob_imp']*100:.1f}%\n"
        f"⚡ *Edge:* +{j['edge']*100:.1f}%\n"
        f"💵 *EV (stake {stake}):* +{j['ev']:.2f}\n"
        f"✅ *Estado:* Recomendada"
    )


# ══════════════════════════════════════════════════════════════
# 4. GENERADOR PRINCIPAL DE RECOMENDACIONES
# ══════════════════════════════════════════════════════════════

def generar_recomendacion(home_id, away_id, home_name, away_name,
                          cuotas=None, stake=STAKE_DEFAULT):
    """
    cuotas: dict con keys btts, over_1_5, over_2_5, over_3_5,
                            home_win, draw, away_win
    """
    sh = calcular_stats(home_id)
    sa = calcular_stats(away_id)

    if not sh or not sa:
        return None

    n       = min(sh["jugados"], sa["jugados"], UMBRAL_PARTIDOS)
    cuotas  = cuotas or {}
    probs   = prob_modelo(sh, sa)

    # Probabilidades brutas por mercado (promedio local+visitante)
    mercados = {
        "btts":     (sh["btts_pct"]  + sa["btts_pct"])  / 2 / 100,
        "over_1_5": (sh["over15_pct"] + sa["over15_pct"]) / 2 / 100,
        "over_2_5": (sh["over25_pct"] + sa["over25_pct"]) / 2 / 100,
        "over_3_5": (sh["over35_pct"] + sa["over35_pct"]) / 2 / 100,
        "home_win": probs["home"],
        "draw":     probs["draw"],
        "away_win": probs["away"],
    }

    labels = {
        "btts":     "Ambos marcan (BTTS)",
        "over_1_5": "Over 1.5 goles",
        "over_2_5": "Over 2.5 goles",
        "over_3_5": "Over 3.5 goles",
        "home_win": f"Victoria {home_name}",
        "draw":     "Empate",
        "away_win": f"Victoria {away_name}",
    }

    jugadas = []
    for key, prob_bot in mercados.items():
        cuota = cuotas.get(key)
        j = evaluar_jugada(labels[key], prob_bot, cuota, stake)
        if j:
            jugadas.append(j)

    return {
        "jugadas": jugadas,
        "probs":   probs,
        "sh":      sh,
        "sa":      sa,
        "n":       n,
    }


# ══════════════════════════════════════════════════════════════
# 5. TEXTO DE ESTADÍSTICAS DE EQUIPO
# ══════════════════════════════════════════════════════════════

def texto_equipo(nombre, s):
    forma_str = " ".join(
        ("🟢" if r == "W" else "🟡" if r == "D" else "🔴")
        for r in s["forma"][:5]
    )
    local = s["local"]
    visit = s["visit"]

    lineas = [
        f"📋 *{nombre}* (últimos {s['jugados']} partidos)",
        f"  Goles: ⬆️ {s['prom_gf']} anotados · ⬇️ {s['prom_gc']} recibidos",
        f"  BTTS: {s['btts_pct']}%  |  Over 1.5: {s['over15_pct']}%  |  Over 2.5: {s['over25_pct']}%  |  Over 3.5: {s['over35_pct']}%",
    ]
    if s["prom_corners"] is not None:
        lineas.append(f"  Corners: {s['prom_corners']} avg  |  Amarillas: {s['prom_amarillas']} avg")
    if local["j"]:
        lineas.append(f"  Local: {local['g']}G {local['e']}E {local['p']}P")
    if visit["j"]:
        lineas.append(f"  Visitante: {visit['g']}G {visit['e']}E {visit['p']}P")
    lineas.append(f"  Forma: {forma_str}  ({s['forma_ponderada']}%)")
    if s["descanso_dias"] is not None:
        lineas.append(f"  Descanso: {s['descanso_dias']} días desde último partido")

    return "\n".join(lineas)
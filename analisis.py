from datetime import datetime
from db import get_partidos_equipo
from config import UMBRAL_BTTS, UMBRAL_OVER25, UMBRAL_PARTIDOS, VENTAJA_MODELO


def calcular_stats(team_id, n=UMBRAL_PARTIDOS):
    filas = get_partidos_equipo(team_id, n)
    if not filas:
        return None

    btts = over15 = over25 = over35 = 0
    goles_a_favor = goles_en_contra = []
    goles_a_favor, goles_en_contra = [], []
    corners_totales = amarillas_totales = []
    forma = []          # lista de resultados: "W", "D", "L"
    fechas = []

    local_j = local_g = local_e = local_p = 0
    visit_j = visit_g = visit_e = visit_p = 0

    for fila in filas:
        gh, ga, home_id, ch, ca, yh, ya, fecha = fila
        if gh is None or ga is None:
            continue

        es_local = home_id == team_id
        gf = gh if es_local else ga   # goles a favor
        gc = ga if es_local else gh   # goles en contra
        total = gh + ga

        goles_a_favor.append(gf)
        goles_en_contra.append(gc)

        if gh > 0 and ga > 0:
            btts += 1
        if total > 1:
            over15 += 1
        if total > 2:
            over25 += 1
        if total > 3:
            over35 += 1

        # Corners y tarjetas (pueden ser None si no hay detalle)
        if ch is not None and ca is not None:
            corners_totales.append(ch + ca)
        if yh is not None and ya is not None:
            amarillas_totales.append(yh + ya)

        # Forma
        if gf > gc:
            forma.append("W")
        elif gf == gc:
            forma.append("D")
        else:
            forma.append("L")

        # Rendimiento local/visitante
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

    # Forma ponderada — partidos más recientes valen más
    pesos = [2 ** i for i in range(len(forma))]   # más reciente = mayor peso
    puntos_forma = sum(
        (3 if r == "W" else 1 if r == "D" else 0) * w
        for r, w in zip(forma, pesos)
    )
    max_puntos = sum(3 * w for w in pesos)
    forma_ponderada = round(puntos_forma / max_puntos * 100, 1) if max_puntos else 0

    # Descanso — días desde el último partido
    descanso = None
    if fechas:
        ultimo = max(fechas)
        try:
            dias = (datetime.utcnow() - datetime.strptime(ultimo, "%Y-%m-%d")).days
            descanso = dias
        except Exception:
            pass

    return {
        "jugados":          j,
        "btts":             btts,
        "btts_pct":         round(btts / j * 100),
        "over15":           over15,
        "over15_pct":       round(over15 / j * 100),
        "over25":           over25,
        "over25_pct":       round(over25 / j * 100),
        "over35":           over35,
        "over35_pct":       round(over35 / j * 100),
        "prom_gf":          round(sum(goles_a_favor) / j, 2),
        "prom_gc":          round(sum(goles_en_contra) / j, 2),
        "prom_corners":     round(sum(corners_totales) / len(corners_totales), 1) if corners_totales else None,
        "prom_amarillas":   round(sum(amarillas_totales) / len(amarillas_totales), 1) if amarillas_totales else None,
        "forma":            forma,           # ["W","W","D","L",...] más reciente primero
        "forma_ponderada":  forma_ponderada, # 0-100
        "local":  {"j": local_j, "g": local_g, "e": local_e, "p": local_p},
        "visit":  {"j": visit_j, "g": visit_g, "e": visit_e, "p": visit_p},
        "descanso_dias":    descanso,
    }


def prob_modelo(sh, sa):
    """
    Estima probabilidad de victoria local/empate/visitante
    basándose en goles promedio (modelo Poisson simplificado).
    """
    import math

    def poisson(lam, k):
        return (lam ** k) * math.exp(-lam) / math.factorial(k)

    lam_h = (sh["prom_gf"] + sa["prom_gc"]) / 2
    lam_a = (sa["prom_gf"] + sh["prom_gc"]) / 2

    p_home = p_draw = p_away = 0.0
    for i in range(8):
        for j in range(8):
            p = poisson(lam_h, i) * poisson(lam_a, j)
            if i > j:   p_home += p
            elif i == j: p_draw += p
            else:        p_away += p

    total = p_home + p_draw + p_away
    return {
        "home": round(p_home / total * 100, 1),
        "draw": round(p_draw / total * 100, 1),
        "away": round(p_away / total * 100, 1),
    }


def generar_recomendacion(home_id, away_id, home_name, away_name, cuotas=None):
    sh = calcular_stats(home_id)
    sa = calcular_stats(away_id)

    if not sh or not sa:
        return None

    n  = min(sh["jugados"], sa["jugados"], UMBRAL_PARTIDOS)
    alertas = []

    btts_avg  = (sh["btts_pct"]  + sa["btts_pct"])  / 2
    over15avg = (sh["over15_pct"] + sa["over15_pct"]) / 2
    over25avg = (sh["over25_pct"] + sa["over25_pct"]) / 2
    over35avg = (sh["over35_pct"] + sa["over35_pct"]) / 2

    if btts_avg  >= UMBRAL_BTTS:
        alertas.append(f"⚽ *Ambos marcan* — {sh['btts']}/{n} local · {sa['btts']}/{n} visit ({btts_avg:.0f}% avg)")
    if over15avg >= 75:
        alertas.append(f"📈 *Over 1.5* — {over15avg:.0f}% avg")
    if over25avg >= UMBRAL_OVER25:
        alertas.append(f"📈 *Over 2.5* — {sh['over25']}/{n} local · {sa['over25']}/{n} visit ({over25avg:.0f}% avg)")
    if over35avg >= 45:
        alertas.append(f"📈 *Over 3.5* — {over35avg:.0f}% avg")

    # Probabilidades del modelo
    probs = prob_modelo(sh, sa)

    # Comparar con cuotas si están disponibles
    ventajas = []
    if cuotas:
        for resultado, label in [("home", f"Victoria {home_name}"), ("draw", "Empate"), ("away", f"Victoria {away_name}")]:
            p_modelo  = probs[resultado]
            p_mercado = cuotas.get(resultado, 0)
            if p_mercado > 0:
                ventaja = p_modelo - p_mercado
                if ventaja >= VENTAJA_MODELO:
                    ventajas.append(f"💡 *Valor: {label}* — modelo {p_modelo}% vs mercado {p_mercado}% (+{ventaja:.1f}%)")

    return {
        "alertas":   alertas,
        "ventajas":  ventajas,
        "probs":     probs,
        "sh":        sh,
        "sa":        sa,
    }


def texto_equipo(nombre, s):
    """Genera el bloque de texto de estadísticas para un equipo."""
    forma_str = " ".join(
        ("🟢" if r == "W" else "🟡" if r == "D" else "🔴")
        for r in s["forma"][:5]
    )
    local  = s["local"]
    visit  = s["visit"]

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
    lineas.append(f"  Forma reciente: {forma_str}  ({s['forma_ponderada']}%)")
    if s["descanso_dias"] is not None:
        lineas.append(f"  Descanso: {s['descanso_dias']} días desde último partido")

    return "\n".join(lineas)
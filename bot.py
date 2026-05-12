import logging
from datetime import datetime, time, timezone

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

import api
import db
import analisis
from config import TELEGRAM_TOKEN, LIGAS, UMBRAL_PARTIDOS, STAKE_DEFAULT

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)


def formato_partido(p, rec, stake=STAKE_DEFAULT):
    home = p["homeTeam"]["name"]
    away = p["awayTeam"]["name"]
    hora = p["utcDate"][11:16]
    liga = p["competition"]["name"]

    if not rec or not rec["jugadas"]:
        return None

    probs = rec["probs"]
    sh    = rec["sh"]
    sa    = rec["sa"]

    lineas = [
        f"🏆 *{liga}*",
        f"🆚 *{home}* vs *{away}* — {hora} UTC",
        f"",
        analisis.texto_equipo(home, sh),
        f"",
        analisis.texto_equipo(away, sa),
        f"",
        f"📊 *Probabilidades del modelo:*",
        f"  Local {probs['home']*100:.1f}%  |  Empate {probs['draw']*100:.1f}%  |  Visit {probs['away']*100:.1f}%",
        f"",
        f"━━━━━━━━━━━━━━━━━━━━",
    ]

    for j in rec["jugadas"]:
        lineas.append("")
        lineas.append(analisis.formatear_jugada(j, stake))
        lineas.append("─────────────────────")

    return "\n".join(lineas)


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db.agregar_suscriptor(update.effective_chat.id)
    await update.message.reply_text(
        "✅ *Bot de alertas de fútbol activado*\n\n"
        "Comandos:\n"
        "/hoy — partidos de hoy con análisis\n"
        "/liga PL — próximos partidos de una liga\n"
        "/equipo Barcelona — análisis detallado de un equipo\n"
        "/stop — dejar de recibir alertas",
        parse_mode="Markdown"
    )


async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db.eliminar_suscriptor(update.effective_chat.id)
    await update.message.reply_text("🔕 Suscripción cancelada.")


async def cmd_hoy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Analizando partidos de hoy...")
    partidos = api.partidos_hoy()

    if not partidos:
        await update.message.reply_text("No hay partidos programados hoy.")
        return

    # Cuotas por liga
    cuotas_por_liga = {}
    ligas_hoy = set(
        p["competition"]["code"]
        for p in partidos
        if p.get("competition", {}).get("code")
    )
    for code in ligas_hoy:
        cuotas_por_liga[code] = api.get_cuotas(code)

    enviados = 0
    for p in partidos:
        db.guardar_partido(p)
        code  = p.get("competition", {}).get("code", "")
        todas = cuotas_por_liga.get(code, {})

        # Buscar cuotas específicas de este partido
        cuota_partido = todas.get(
            (p["homeTeam"]["name"], p["awayTeam"]["name"]), {}
        )

        rec = analisis.generar_recomendacion(
            p["homeTeam"]["id"], p["awayTeam"]["id"],
            p["homeTeam"]["name"], p["awayTeam"]["name"],
            cuotas=cuota_partido
        )
        msg = formato_partido(p, rec)
        if msg:
            await update.message.reply_text(msg, parse_mode="Markdown")
            enviados += 1

    if enviados == 0:
        await update.message.reply_text("📭 Sin jugadas con valor para hoy.")


async def cmd_equipo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text(
            "Uso: `/equipo <nombre>`\nEjemplos:\n"
            "`/equipo Real Madrid`\n"
            "`/equipo Barcelona`\n"
            "`/equipo Liverpool`",
            parse_mode="Markdown"
        )
        return

    nombre = " ".join(ctx.args)
    await update.message.reply_text(f"⏳ Buscando `{nombre}`...", parse_mode="Markdown")

    # Buscar en todas las ligas
    equipo = api.buscar_equipo_global(nombre)

    if not equipo:
        await update.message.reply_text(
            f"❌ No encontré `{nombre}`.\n\n"
            f"Prueba con el nombre en inglés:\n"
            f"• Real Madrid → `Real Madrid` ✅\n"
            f"• Barça → `Barcelona` ✅\n"
            f"• PSG → `Paris` ✅",
            parse_mode="Markdown"
        )
        return

    team_id   = equipo["id"]
    team_name = equipo["name"]

    # Verificar si hay historial, si no cargar desde la API
    s = analisis.calcular_stats(team_id)
    if not s:
        await update.message.reply_text(
            f"📥 Sin historial local para *{team_name}*. Cargando partidos recientes...",
            parse_mode="Markdown"
        )
        partidos = api.cargar_historial_equipo(team_id, n=20)
        for p in partidos:
            try:
                db.guardar_partido(p)
            except Exception:
                pass
        s = analisis.calcular_stats(team_id)

    if not s:
        await update.message.reply_text(
            f"⚠️ No hay datos suficientes para *{team_name}* en este momento.",
            parse_mode="Markdown"
        )
        return

    msg = analisis.texto_equipo(team_name, s)
    await update.message.reply_text(msg, parse_mode="Markdown")

    


async def cmd_liga(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if not args:
        ligas_txt = "\n".join(f"  `{v}` — {k}" for k, v in LIGAS.items())
        await update.message.reply_text(
            f"Uso: `/liga <código>`\n\nCódigos:\n{ligas_txt}",
            parse_mode="Markdown"
        )
        return

    code = args[0].upper()
    if code not in LIGAS.values():
        await update.message.reply_text(f"Liga `{code}` no reconocida.", parse_mode="Markdown")
        return

    partidos = api.proximos_partidos(code, dias=3)
    if not partidos:
        await update.message.reply_text("Sin partidos en los próximos 3 días.")
        return

    for p in partidos[:5]:
        home  = p["homeTeam"]["name"]
        away  = p["awayTeam"]["name"]
        fecha = p["utcDate"][:10]
        hora  = p["utcDate"][11:16]
        await update.message.reply_text(
            f"📅 *{fecha}* {hora} UTC\n{home} vs {away}",
            parse_mode="Markdown"
        )

async def cmd_cargar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Carga historial de todos los equipos de una liga."""
    args = ctx.args
    if not args:
        await update.message.reply_text(
            "Uso: `/cargar PL`\nCarga historial de todos los equipos de esa liga.",
            parse_mode="Markdown"
        )
        return

    code = args[0].upper()
    await update.message.reply_text(
        f"⏳ Cargando historial de *{code}*... esto tarda ~2 minutos.",
        parse_mode="Markdown"
    )

    try:
        data = api.get(f"competitions/{code}/teams")
        equipos = data.get("teams", [])
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
        return

    cargados = 0
    for equipo in equipos:
        try:
            partidos = api.cargar_historial_equipo(equipo["id"], n=15)
            for p in partidos:
                db.guardar_partido(p)
            cargados += 1
        except Exception:
            continue

    await update.message.reply_text(
        f"✅ Historial cargado: *{cargados}/{len(equipos)}* equipos de *{code}*\n"
        f"Ya puedes usar `/equipo <nombre>` con cualquier equipo de esa liga.",
        parse_mode="Markdown"
    )


async def job_actualizar_datos(ctx: ContextTypes.DEFAULT_TYPE):
    """
    Corre cada noche a las 02:00 UTC.
    Actualiza resultados de los últimos 3 días en la DB.
    """
    log.info("Actualizando historial de partidos...")
    
    partidos = api.partidos_recientes(dias=3)
    actualizados = nuevos = 0
    
    for p in partidos:
        try:
            gh = p["score"]["fullTime"].get("home")
            ga = p["score"]["fullTime"].get("away")
            
            if db.partido_existe(p["id"]):
                db.actualizar_resultado(p["id"], gh, ga, p["status"])
                actualizados += 1
            else:
                db.guardar_partido(p)
                nuevos += 1
        except Exception as e:
            log.warning(f"Error actualizando partido {p.get('id')}: {e}")
    
    log.info(f"Actualización: {nuevos} nuevos, {actualizados} actualizados")


async def job_alertas_diarias(ctx: ContextTypes.DEFAULT_TYPE):
    """
    Corre cada día a las 08:00 UTC.
    Envía alertas de partidos del día a todos los suscriptores.
    """
    log.info("Ejecutando alertas diarias...")
    partidos     = api.partidos_hoy()
    suscriptores = db.get_suscriptores()

    if not partidos or not suscriptores:
        return

    mensajes = []
    for p in partidos:
        db.guardar_partido(p)
        rec = analisis.generar_recomendacion(
            p["homeTeam"]["id"], p["awayTeam"]["id"],
            p["homeTeam"]["name"], p["awayTeam"]["name"]
        )
        msg = formato_partido(p, rec)
        if msg:
            mensajes.append(msg)

    if not mensajes:
        return

    encabezado = f"🌅 *Alertas del día — {datetime.utcnow().strftime('%d/%m/%Y')}*\n━━━━━━━━━━━━━━━━━━━━"
    for chat_id in suscriptores:
        try:
            await ctx.bot.send_message(chat_id, encabezado, parse_mode="Markdown")
            for msg in mensajes:
                await ctx.bot.send_message(chat_id, msg, parse_mode="Markdown")
        except Exception as e:
            log.warning(f"Error enviando a {chat_id}: {e}")

async def cmd_actualizar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Actualiza manualmente el historial de los últimos 7 días."""
    await update.message.reply_text("⏳ Actualizando historial de partidos...")
    
    partidos = api.partidos_recientes(dias=7)
    actualizados = nuevos = 0
    
    for p in partidos:
        try:
            gh = p["score"]["fullTime"].get("home")
            ga = p["score"]["fullTime"].get("away")
            
            if db.partido_existe(p["id"]):
                db.actualizar_resultado(p["id"], gh, ga, p["status"])
                actualizados += 1
            else:
                db.guardar_partido(p)
                nuevos += 1
        except Exception as e:
            continue
    
    await update.message.reply_text(
        f"✅ *Historial actualizado*\n"
        f"  Partidos nuevos: {nuevos}\n"
        f"  Resultados actualizados: {actualizados}",
        parse_mode="Markdown"
    )

# En bot.py — agrega este comando
async def cmd_cuotas(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Uso: /cuotas Liverpool Chelsea btts:1.72 over_2_5:1.67 home_win:2.10 draw:3.40 away_win:3.20
    """
    if not ctx.args or len(ctx.args) < 3:
        await update.message.reply_text(
            "Uso:\n`/cuotas <local> vs <visitante> btts:1.72 over_2_5:1.67 home_win:2.10`\n\n"
            "Mercados disponibles:\n"
            "`btts` `over_1_5` `over_2_5` `over_3_5` `home_win` `draw` `away_win`",
            parse_mode="Markdown"
        )
        return

    texto = " ".join(ctx.args)

    # Separar equipos de cuotas
    cuotas = {}
    equipos_partes = []
    for parte in ctx.args:
        if ":" in parte:
            key, val = parte.split(":", 1)
            try:
                cuotas[key.lower()] = float(val)
            except ValueError:
                pass
        else:
            equipos_partes.append(parte)

    nombre_partido = " ".join(equipos_partes)
    await update.message.reply_text(
        f"⏳ Analizando *{nombre_partido}* con cuotas de Wplay...",
        parse_mode="Markdown"
    )

    # Buscar los dos equipos
    partes = nombre_partido.lower().split(" vs ")
    if len(partes) != 2:
        await update.message.reply_text(
            "Formato: `LocalTeam vs AwayTeam btts:1.72 ...`",
            parse_mode="Markdown"
        )
        return

    home_nombre = partes[0].strip()
    away_nombre = partes[1].strip()

    home_eq = api.buscar_equipo_global(home_nombre)
    away_eq = api.buscar_equipo_global(away_nombre)

    if not home_eq or not away_eq:
        await update.message.reply_text("❌ No encontré uno o ambos equipos.")
        return

    rec = analisis.generar_recomendacion(
        home_eq["id"], away_eq["id"],
        home_eq["name"], away_eq["name"],
        cuotas=cuotas
    )

    if not rec or not rec["jugadas"]:
        await update.message.reply_text(
            "📭 Ninguna jugada supera los filtros de valor con esas cuotas."
        )
        return

    probs = rec["probs"]
    lineas = [
        f"🆚 *{home_eq['name']}* vs *{away_eq['name']}*",
        f"📊 Modelo: Local {probs['home']*100:.1f}% | Empate {probs['draw']*100:.1f}% | Visit {probs['away']*100:.1f}%",
        f"━━━━━━━━━━━━━━━━━━━━",
    ]
    for j in rec["jugadas"]:
        lineas.append("")
        lineas.append(analisis.formatear_jugada(j))
        lineas.append("─────────────────────")

    await update.message.reply_text("\n".join(lineas), parse_mode="Markdown")

async def cmd_top(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Muestra el Top 5 picks del día según métricas internas."""
    await update.message.reply_text("⏳ Analizando partidos del día...")

    partidos = api.partidos_hoy()
    if not partidos:
        await update.message.reply_text("No hay partidos programados hoy.")
        return

    # Guardar partidos en DB
    for p in partidos:
        try:
            db.guardar_partido(p)
        except Exception:
            pass

    top = analisis.get_top_picks(partidos, top_n=5)

    if not top:
        await update.message.reply_text(
            "📭 No hay picks válidos hoy según los filtros actuales.\n"
            "Puede que falte historial — usa `/cargar PL` para cargar datos."
        )
        return

    lineas = ["🔥 *TOP 5 PICKS DEL DÍA*\n"]

    for i, pick in enumerate(top, 1):
        estado_emoji = "🔵" if pick["estado"] == "Apta" else "🟢"
        lineas.append(
            f"{i}) *{pick['partido']}*\n"
            f"   🏆 {pick['liga']} — {pick['hora']} UTC\n"
            f"   📌 Mercado: {pick['mercado']}\n"
            f"   🤖 Prob. bot: {pick['prob_bot']*100:.1f}%\n"
            f"   📊 Soporte reciente: {pick['soporte']}\n"
            f"   🧠 Score interno: {pick['score']}/10\n"
            f"   {estado_emoji} Estado: {pick['estado']}\n"
        )

    lineas.append("━━━━━━━━━━━━━━━━━━━━")
    lineas.append("_Picks basados en estadísticas recientes. No es asesoría financiera._")

    await update.message.reply_text("\n".join(lineas), parse_mode="Markdown")


def main():
    db.init_db()

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("stop",   cmd_stop))
    app.add_handler(CommandHandler("hoy",    cmd_hoy))
    app.add_handler(CommandHandler("liga",   cmd_liga))
    app.add_handler(CommandHandler("equipo", cmd_equipo))
    app.add_handler(CommandHandler("cargar", cmd_cargar))
    app.add_handler(CommandHandler("actualizar", cmd_actualizar))
    app.add_handler(CommandHandler("cuotas", cmd_cuotas))
    app.add_handler(CommandHandler("top", cmd_top))


    app.job_queue.run_daily(
        job_actualizar_datos,
        time=time(hour=2, minute=0, tzinfo=timezone.utc),
        name="actualizar_datos"
    )

    log.info("Bot iniciado.")
    app.run_polling()


if __name__ == "__main__":
    main()
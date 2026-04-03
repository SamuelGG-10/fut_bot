import logging
from datetime import datetime, time, timezone

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

import api
import db
import analisis
from config import TELEGRAM_TOKEN, LIGAS, UMBRAL_PARTIDOS

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)


def formato_partido(p, rec):
    home = p["homeTeam"]["name"]
    away = p["awayTeam"]["name"]
    hora = p["utcDate"][11:16]
    liga = p["competition"]["name"]

    if not rec:
        return None

    sh = rec["sh"]
    sa = rec["sa"]
    probs = rec["probs"]

    # Solo enviar si hay alertas o ventajas de valor
    if not rec["alertas"] and not rec["ventajas"]:
        return None

    lineas = [
        f"🏆 *{liga}*",
        f"🆚 *{home}* vs *{away}* — {hora} UTC",
        f"",
        analisis.texto_equipo(home, sh),
        f"",
        analisis.texto_equipo(away, sa),
        f"",
        f"📊 *Probabilidades del modelo:*",
        f"  Local {probs['home']}%  |  Empate {probs['draw']}%  |  Visit {probs['away']}%",
    ]

    if rec["alertas"]:
        lineas.append(f"\n🔔 *Jugadas detectadas:*")
        lineas += [f"  {a}" for a in rec["alertas"]]

    if rec["ventajas"]:
        lineas.append(f"\n💰 *Valor vs mercado:*")
        lineas += [f"  {v}" for v in rec["ventajas"]]

    lineas.append("━━━━━━━━━━━━━━━━━━━━")
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

    # Obtener cuotas por liga
    cuotas_por_liga = {}
    ligas_hoy = set(p["competition"]["code"] for p in partidos if p.get("competition", {}).get("code"))
    for code in ligas_hoy:
        cuotas_por_liga[code] = api.get_cuotas(code)

    enviados = 0
    for p in partidos:
        db.guardar_partido(p)
        code   = p.get("competition", {}).get("code", "")
        cuotas = cuotas_por_liga.get(code, {})

        # Buscar cuota de este partido específico
        cuota_partido = cuotas.get(
            (p["homeTeam"]["name"], p["awayTeam"]["name"]),
            None
        )

        rec = analisis.generar_recomendacion(
            p["homeTeam"]["id"], p["awayTeam"]["id"],
            p["homeTeam"]["name"], p["awayTeam"]["name"],
            cuota_partido
        )
        msg = formato_partido(p, rec)
        if msg:
            await update.message.reply_text(msg, parse_mode="Markdown")
            enviados += 1

    if enviados == 0:
        await update.message.reply_text("📭 Sin jugadas con alto porcentaje para hoy.")


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


async def job_alertas_diarias(ctx: ContextTypes.DEFAULT_TYPE):
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


def main():
    db.init_db()

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("stop",   cmd_stop))
    app.add_handler(CommandHandler("hoy",    cmd_hoy))
    app.add_handler(CommandHandler("liga",   cmd_liga))
    app.add_handler(CommandHandler("equipo", cmd_equipo))
    app.add_handler(CommandHandler("cargar", cmd_cargar))

    app.job_queue.run_daily(
        job_alertas_diarias,
        time=time(hour=8, minute=0, tzinfo=timezone.utc),
        name="alertas_diarias"
    )

    log.info("Bot iniciado.")
    app.run_polling()


if __name__ == "__main__":
    main()
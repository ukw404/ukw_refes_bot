import os
import time
import asyncio
import logging
from flask import Flask, request
from telegram import Update, InputMediaPhoto, InputMediaVideo
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# ── Community config ───────────────────────────────────────────────────────────
ID_SUPERGRUPO = -1003173754617
ID_TEMA_REFES = 12

# ── Flask Web Server ───────────────────────────────────────────────────────────
flask_app = Flask(__name__)
ptb_application = None

@flask_app.route("/")
def health():
    return "Bot UkW Activo via Webhook Nativo", 200

@flask_app.route("/webhook", methods=["POST"])
def webhook():
    """Recibe las actualizaciones de Telegram y las procesa de forma segura"""
    global ptb_application
    if ptb_application:
        try:
            # Convertimos los datos recibidos en un objeto Update de Telegram
            update = Update.de_json(request.get_json(force=True), ptb_application.bot)
            
            # SOLUCIÓN CRÍTICA: Ejecutamos de forma síncrona/aislada para Flask
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(ptb_application.process_update(update))
            loop.close()
            
        except Exception as e:
            logging.error("Error procesando actualización en webhook: %s", e)
            
    return "OK", 200

# ── Async album accumulator ───────────────────────────────────────────────────
CACHE_TTL: int = 600
_album: dict[str, dict] = {}

def _prune():
    cutoff = time.time() - CACHE_TTL
    stale  = [k for k, v in _album.items() if v["ts"] < cutoff]
    for k in stale:
        del _album[k]

async def accumulate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.media_group_id:
        return
    mgid = msg.media_group_id
    if mgid not in _album:
        _album[mgid] = {"msgs": [], "ts": time.time()}
    known = {m.message_id for m in _album[mgid]["msgs"]}
    if msg.message_id not in known:
        _album[mgid]["msgs"].append(msg)
        _album[mgid]["ts"] = time.time()
    _prune()

# ── Helpers ────────────────────────────────────────────────────────────────────
def user_mention(user) -> str:
    if user.username:
        return f"@{user.username}"
    return f'<a href="tg://user?id={user.id}">{user.first_name}</a>'

def make_caption(original: str | None, mention: str) -> str:
    base   = original.strip() if original else ""
    suffix = f"✨ Referencia enviada por: {mention}"
    return f"{base}\n\n{suffix}" if base else suffix

def as_input_media(msg, caption: str | None, parse_mode: str | None):
    if msg.photo:
        return InputMediaPhoto(media=msg.photo[-1].file_id, caption=caption, parse_mode=parse_mode)
    if msg.video:
        return InputMediaVideo(media=msg.video.file_id, caption=caption, parse_mode=parse_mode)
    return None

# ── Core handler ───────────────────────────────────────────────────────────────
_ERROR = "❌ Usa este comando respondiendo a una *foto, video o GIF* que quieras enviar."

async def mover_referencia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trigger = update.message
    if not trigger:
        return

    async def reject():
        err = await trigger.reply_text(_ERROR, parse_mode="Markdown")
        await asyncio.sleep(5)
        for m in (err, trigger):
            try:
                await m.delete()
            except Exception:
                pass

    if not trigger.reply_to_message:
        await reject()
        return

    target = trigger.reply_to_message

    if not (target.photo or target.video or target.animation or target.document):
        await reject()
        return

    mention = user_mention(trigger.from_user)
    caption = make_caption(target.caption, mention)
    mgid    = target.media_group_id

    try:
        if mgid:
            await asyncio.sleep(1.5)
            parts = list(_album.get(mgid, {}).get("msgs", []))
            if target.message_id not in {m.message_id for m in parts}:
                parts.append(target)
            parts.sort(key=lambda m: m.message_id)

            media_list = []
            for i, part in enumerate(parts):
                item = as_input_media(part, caption=caption if i == 0 else None, parse_mode="HTML" if i == 0 else None)
                if item is not None:
                    media_list.append(item)

            if not media_list:
                raise ValueError("Album had no photos or videos to forward.")

            await context.bot.send_media_group(chat_id=ID_SUPERGRUPO, media=media_list, message_thread_id=ID_TEMA_REFES)
            stamp = f"✅ ¡Este álbum fue guardado con éxito por {mention} en el tema de Refes!"

        else:
            await context.bot.copy_message(
                chat_id=ID_SUPERGRUPO, from_chat_id=trigger.chat_id, message_id=target.message_id,
                message_thread_id=ID_TEMA_REFES, caption=caption, parse_mode="HTML"
            )
            stamp = f"✅ ¡Esta referencia fue guardada con éxito por {mention} en el tema de Refes!"

        try:
            await trigger.delete()
        except Exception:
            pass

        await target.reply_text(stamp, parse_mode="HTML")

    except Exception as exc:
        logging.error("Error while copying reference: %s", exc)

# ── Entry point ────────────────────────────────────────────────────────────────
def main():
    global ptb_application
    token = os.environ.get("TOKEN")
    render_url = os.environ.get("RENDER_EXTERNAL_URL") 

    if not token:
        print("❌ ERROR: TOKEN environment variable is not set.")
        return

    # Creamos un bucle temporal solo para inicializar el bot de Telegram
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    ptb_application = Application.builder().token(token).build()

    ptb_application.add_handler(MessageHandler((filters.PHOTO | filters.VIDEO) & filters.ChatType.GROUPS, accumulate), group=-1)
    ptb_application.add_handler(CommandHandler("refe", mover_referencia))
    ptb_application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"(?i)^\.refe"), mover_referencia))

    # Inicialización interna de componentes
    loop.run_until_complete(ptb_application.initialize())
    loop.run_until_complete(ptb_application.start())

    # Registrar la dirección del Webhook en los servidores de Telegram
    if render_url:
        webhook_url = f"{render_url.rstrip('/')}/webhook"
        loop.run_until_complete(ptb_application.bot.set_webhook(url=webhook_url, allowed_updates=Update.ALL_TYPES))
        print(f"🚀 Webhook configurado con éxito en: {webhook_url}")
    else:
        print("⚠️ Nota: Ejecutándose localmente, RENDER_EXTERNAL_URL no detectada.")

    loop.close()

    print("🚀 Servidor Flask en marcha. Escuchando peticiones HTTP de Telegram...")
    port = int(os.environ.get("PORT", 8000))
    flask_app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
    

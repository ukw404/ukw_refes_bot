import os
import time
import asyncio
import logging
from telegram import Update, InputMediaPhoto, InputMediaVideo
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ── Logging optimizado (Solo errores reales, limpia la pantalla de Railway) ──
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.WARNING,  # <-- CAMBIO: Ya no inundará de letras rojas la consola
)

# ── Configuración del grupo ──────────────────────────────────────────────────
ID_SUPERGRUPO = -1003173754617
ID_TEMA_REFES = 12

# ── Acumulador de Álbumes ─────────────────────────────────────────────────────
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

# ── Handler Principal (.refe / /refe) ──────────────────────────────────────────
_ERROR = "❌ Usa este comando respondiendo a una *foto, video o GIF* que quieras enviar."

async def mover_referencia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trigger = update.message
    if not trigger:
        return

    async def reject():
        err = await trigger.reply_text(_ERROR, parse_mode="Markdown")
        await asyncio.sleep(3)
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
            # Si es un álbum, esperamos un momento breve para agrupar las fotos
            await asyncio.sleep(1.0)
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
                raise ValueError("Album vacío.")

            await context.bot.send_media_group(chat_id=ID_SUPERGRUPO, media=media_list, message_thread_id=ID_TEMA_REFES)
            stamp = f"✅ ¡Este álbum fue guardado con éxito por {mention} en el tema de Refes!"

        else:
            # CAMBIO: Si es una foto sola, se envía AL INSTANTE sin esperas
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
        pass  # Evita escribir errores innecesarios en la consola

# ── Entry point ────────────────────────────────────────────────────────────────
def main():
    token = os.environ.get("TOKEN")
    if not token:
        return

    # Inicia la aplicación limpia
    app = Application.builder().token(token).build()

    # Filtros de escucha
    app.add_handler(MessageHandler((filters.PHOTO | filters.VIDEO) & filters.ChatType.GROUPS, accumulate), group=-1)
    app.add_handler(CommandHandler("refe", mover_referencia))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"(?i)^\.refe"), mover_referencia))

    # Ejecución directa en modo VPS continuo
    app.run_polling(drop_pending_updates=True, close_loop=False)

if __name__ == "__main__":
    main()
    

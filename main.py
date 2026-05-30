import os
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

# Mantener la consola limpia de Railway
logging.basicConfig(level=logging.WARNING)

ID_SUPERGRUPO = -1003173754617
ID_TEMA_REFES = 12

# Acumulador optimizado para álbumes
CACHE_TTL: int = 300
_album: dict[str, dict] = {}

async def accumulate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.media_group_id:
        return
    mgid = msg.media_group_id
    if mgid not in _album:
        _album[mgid] = {"msgs": [], "ts": asyncio.get_event_loop().time()}
    
    known = {m.message_id for m in _album[mgid]["msgs"]}
    if msg.message_id not in known:
        _album[mgid]["msgs"].append(msg)
        _album[mgid]["ts"] = asyncio.get_event_loop().time()

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

# ── PROCESO ASÍNCRONO CORREGIDO ──
async def proceso_subterrano_copia(context, chat_id, target, trigger, mention, caption, mgid):
    # Lanzamos el borrado del comando en paralelo con una mini espera para asegurar el tiro
    async def borrar_comando():
        await asyncio.sleep(0.2) # Pausa de milisegundos para que Telegram registre el mensaje
        try:
            await trigger.delete()
        except:
            pass

    # Creamos la tarea de borrado de fondo inmediatamente
    asyncio.create_task(borrar_comando())

    try:
        if mgid:
            # Si es álbum, espera 1 segundo de agrupación dedicada
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

            if media_list:
                await context.bot.send_media_group(chat_id=ID_SUPERGRUPO, media=media_list, message_thread_id=ID_TEMA_REFES)
                stamp = f"✅ ¡Este álbum fue guardado con éxito por {mention} en el tema de Refes!"
                await target.reply_text(stamp, parse_mode="HTML")
        else:
            # Si es una sola foto, copia directa instantánea
            await context.bot.copy_message(
                chat_id=ID_SUPERGRUPO, from_chat_id=chat_id, message_id=target.message_id,
                message_thread_id=ID_TEMA_REFES, caption=caption, parse_mode="HTML"
            )
            stamp = f"✅ ¡Esta referencia fue guardada con éxito por {mention} en el tema de Refes!"
            await target.reply_text(stamp, parse_mode="HTML")
            
    except Exception as e:
        print(f"Error en copia: {e}")

# ── HANDLER PRINCIPAL ──
async def mover_referencia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trigger = update.message
    if not trigger:
        return

    if not trigger.reply_to_message:
        err = await trigger.reply_text("❌ Responde a una foto o video.", parse_mode="Markdown")
        await asyncio.sleep(3)
        try:
            await err.delete()
            await trigger.delete()
        except: pass
        return

    target = trigger.reply_to_message
    if not (target.photo or target.video or target.animation or target.document):
        return

    mention = user_mention(trigger.from_user)
    caption = make_caption(target.caption, mention)
    mgid    = target.media_group_id

    # Lanzamos toda la operación al subsuelo. El grupo sigue fluyendo rápido.
    asyncio.create_task(
        proceso_subterrano_copia(
            context, trigger.chat_id, target, trigger, mention, caption, mgid
        )
    )

def main():
    token = os.environ.get("TOKEN")
    if not token:
        return

    app = Application.builder().token(token).build()

    app.add_handler(MessageHandler((filters.PHOTO | filters.VIDEO) & filters.ChatType.GROUPS, accumulate), group=-1)
    app.add_handler(CommandHandler("refe", mover_referencia))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"(?i)^\.refe"), mover_referencia))

    app.run_polling(drop_pending_updates=True, close_loop=False)

if __name__ == "__main__":
    main()
    

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

# Mantener la consola de Railway limpia de alertas informativas basura
logging.basicConfig(level=logging.WARNING)

ID_SUPERGRUPO = -1003173754617
ID_TEMA_REFES = 12

# Memoria global persistente para los álbumes
_album: dict[str, list] = {}
_album_locks: dict[str, bool] = {}

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

# ── ACUMULADOR SEGURO DE MEDIA ──
async def accumulate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.media_group_id:
        return
        
    mgid = msg.media_group_id
    
    if mgid not in _album:
        _album[mgid] = []
        
    # Agrega la foto o video si no estaba registrado ya
    if msg.message_id not in {m.message_id for m in _album[mgid]}:
        _album[mgid].append(msg)

# ── PROCESADOR ASÍNCRONO DE ÁLBUMES COMPLETOS ──
async def procesar_y_enviar_album(context, chat_id, mgid, trigger, target, mention, caption):
    # Si esta tarea ya se está ejecutando para este álbum, no la duplicamos
    if _album_locks.get(mgid):
        return
    _album_locks[mgid] = True

    # ⚡ TIEMPO SEGURO: Esperamos 3.5 segundos completos para que entren las 5 fotos completas
    await asyncio.sleep(3.5)
    
    try:
        # Obtenemos todas las fotos que el acumulador guardó en este tiempo
        parts = _album.get(mgid, [])
        
        # Nos aseguramos de incluir la foto a la que se le dio responder originalmente
        if target.message_id not in {m.message_id for m in parts}:
            parts.append(target)
            
        # Ordenamos las imágenes por ID para mantener el orden estético del usuario
        parts.sort(key=lambda m: m.message_id)

        media_list = []
        for i, part in enumerate(parts):
            # Solo la primera foto lleva el texto descriptivo, las demás van limpias (Regla de Telegram)
            item = as_input_media(part, caption=caption if i == 0 else None, parse_mode="HTML" if i == 0 else None)
            if item is not None:
                media_list.append(item)

        if media_list:
            await context.bot.send_media_group(chat_id=ID_SUPERGRUPO, media=media_list, message_thread_id=ID_TEMA_REFES)
            stamp = f"✅ ¡Este álbum de {len(media_list)} fotos fue guardado con éxito por {mention} en el tema de Refes!"
            await target.reply_text(stamp, parse_mode="HTML")
            
            # Borramos el comando .refe una vez completada la migración del álbum
            try: await trigger.delete()
            except: pass
            
    except Exception as e:
        print(f"Error procesando álbum de fondo: {e}")
    finally:
        # Limpieza de memoria una vez enviado
        if mgid in _album: del _album[mgid]
        if mgid in _album_locks: del _album_locks[mgid]

# ── HANDLER PRINCIPAL ──
async def mover_referencia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trigger = update.message
    if not trigger or not trigger.reply_to_message:
        return

    target = trigger.reply_to_message
    if not (target.photo or target.video or target.animation or target.document):
        return

    mention = user_mention(trigger.from_user)
    caption = make_caption(target.caption, mention)
    mgid    = target.media_group_id

    if mgid:
        # Si es un álbum, lanzamos la tarea pesada al subsuelo con bloqueo de duplicados
        asyncio.create_task(
            procesar_y_enviar_album(context, trigger.chat_id, mgid, trigger, target, mention, caption)
        )
    else:
        # Si es una sola foto individual, se ejecuta AL INSTANTE en 0.1 segundos sin esperas
        try:
            try: asyncio.create_task(trigger.delete())
            except: pass
            
            await context.bot.copy_message(
                chat_id=ID_SUPERGRUPO, from_chat_id=trigger.chat_id, message_id=target.message_id,
                message_thread_id=ID_TEMA_REFES, caption=caption, parse_mode="HTML"
            )
            await target.reply_text(f"✅ ¡Esta referencia fue guardada con éxito por {mention} en el tema de Refes!", parse_mode="HTML")
        except Exception as e:
            print(f"Error en foto individual: {e}")

def main():
    token = os.environ.get("TOKEN")
    if not token:
        return

    app = Application.builder().token(token).build()

    # El acumulador se registra primero para interceptar toda la multimedia del grupo
    app.add_handler(MessageHandler((filters.PHOTO | filters.VIDEO) & filters.ChatType.GROUPS, accumulate), group=-1)
    app.add_handler(CommandHandler("refe", mover_referencia))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"(?i)^\.refe"), mover_referencia))

    # drop_pending_updates=True limpia mensajes viejos acumulados durante crasheos
    app.run_polling(drop_pending_updates=True, close_loop=False)

if __name__ == "__main__":
    main()
    

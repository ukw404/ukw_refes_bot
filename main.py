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

# Consola limpia en Railway
logging.basicConfig(level=logging.WARNING)

ID_SUPERGRUPO = -1003173754617
ID_TEMA_REFES = 12

# Estructura inteligente para controlar los álbumes
_album: dict[str, dict] = {}

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

# ── ACUMULADOR INTELIGENTE CORREGIDO ──
async def accumulate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.media_group_id:
        return
        
    mgid = msg.media_group_id
    
    # Si es la primera foto del álbum que llega, preparamos el espacio
    if mgid not in _album:
        _album[mgid] = {
            "msgs": [],
            "trigger_seen": False,  # Guarda si el usuario ya puso .refe
            "user_mention": "",
            "trigger_msg": None,
            "target_caption": msg.caption or ""
        }
    
    # Guardamos la foto en la lista si no existía
    if msg.message_id not in {m.message_id for m in _album[mgid]["msgs"]}:
        _album[mgid]["msgs"].append(msg)
        
    # Si el usuario ya puso el comando .refe antes o durante la subida, disparamos el empaquetado
    if _album[mgid]["trigger_seen"]:
        await procesar_album_completo(context, mgid)

# Función dedicada a esperar y enviar todo el paquete junto
async def procesar_album_completo(context, mgid):
    # Damos 2 segundos completos para asegurar que entren las 5 fotos completas a la memoria
    await asyncio.sleep(2.0)
    
    data = _album.get(mgid)
    if not data or not data["msgs"]:
        return
        
    # Evitamos que se envíe dos veces si entran más actualizaciones
    _album[mgid] = {"msgs": []} 
    
    parts = data["msgs"]
    parts.sort(key=lambda m: m.message_id)
    
    mention = data["user_mention"]
    caption = make_caption(data["target_caption"], mention)
    
    media_list = []
    for i, part in enumerate(parts):
        item = as_input_media(part, caption=caption if i == 0 else None, parse_mode="HTML" if i == 0 else None)
        if item is not None:
            media_list.append(item)
            
    try:
        if media_list:
            await context.bot.send_media_group(chat_id=ID_SUPERGRUPO, media=media_list, message_thread_id=ID_TEMA_REFES)
            stamp = f"✅ ¡Este álbum de {len(media_list)} fotos fue guardado por {mention}!"
            if parts:
                await parts[0].reply_text(stamp, parse_mode="HTML")
            if data["trigger_msg"]:
                try: await data["trigger_msg"].delete()
                except: pass
    except Exception as e:
        print(f"Error procesando álbum: {e}")

# ── HANDLER PRINCIPAL ──
async def mover_referencia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trigger = update.message
    if not trigger or not trigger.reply_to_message:
        return

    target = trigger.reply_to_message
    mention = user_mention(trigger.from_user)
    mgid = target.media_group_id

    if mgid:
        # Si es un álbum, inicializamos el registro si no existe
        if mgid not in _album:
            _album[mgid] = {
                "msgs": [target],
                "trigger_seen": True,
                "user_mention": mention,
                "trigger_msg": trigger,
                "target_caption": target.caption or ""
            }
        else:
            _album[mgid]["trigger_seen"] = True
            _album[mgid]["user_mention"] = mention
            _album[mgid]["trigger_msg"] = trigger
            if target.caption:
                _album[mgid]["target_caption"] = target.caption
                
        # Activamos la espera asíncrona dedicada de fondo
        asyncio.create_task(procesar_album_completo(context, mgid))
    else:
        # Si es una sola foto individual, se ejecuta AL INSTANTE en 0.1 segundos
        caption = make_caption(target.caption, mention)
        try:
            try: asyncio.create_task(trigger.delete())
            except: pass
            
            await context.bot.copy_message(
                chat_id=ID_SUPERGRUPO, from_chat_id=trigger.chat_id, message_id=target.message_id,
                message_thread_id=ID_TEMA_REFES, caption=caption, parse_mode="HTML"
            )
            await target.reply_text(f"✅ ¡Esta referencia fue guardada con éxito por {mention}!", parse_mode="HTML")
        except Exception as e:
            print(f"Error en foto sola: {e}")

def main():
    token = os.environ.get("TOKEN")
    if not token:
        return

    app = Application.builder().token(token).build()

    # Patrullaje estricto de hilos
    app.add_handler(MessageHandler((filters.PHOTO | filters.VIDEO) & filters.ChatType.GROUPS, accumulate), group=-1)
    app.add_handler(CommandHandler("refe", mover_referencia))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"(?i)^\.refe"), mover_referencia))

    # Aseguramos que tumbe cualquier proceso zombie colgado en Railway
    app.run_polling(drop_pending_updates=True, close_loop=True)

if __name__ == "__main__":
    main()
    

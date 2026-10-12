import json
import os
import sqlite3
import time
import urllib.request

TOKEN = os.environ["BOT_TOKEN"].strip()
ADMIN = int(os.environ.get("ADMIN_ID", "0"))
CHANNEL = "@saricamdanbihaber"
CHANNEL_URL = "https://t.me/saricamdanbihaber"

db = sqlite3.connect(os.environ.get("DB_PATH", "bot.db"))
db.execute(
    "CREATE TABLE IF NOT EXISTS decisions "
    "(item TEXT PRIMARY KEY, status TEXT)"
)
db.commit()

categories = {}

MENU = {
    "keyboard": [
        ["📰 Haber Gönder", "🔎 Kayıp İlanı"],
        ["📢 Haber Kanalı", "❌ İptal"]
    ],
    "resize_keyboard": True
}


def api(method, **data):
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{TOKEN}/{method}",
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        result = json.load(response)
    if not result.get("ok"):
        raise RuntimeError("Telegram işlemi başarısız.")
    return result["result"]


def say(chat, text, **extra):
    return api("sendMessage", chat_id=chat, text=text, **extra)


def membership_ok(chat):
    if chat == ADMIN:
        return True

    try:
        member = api("getChatMember", chat_id=CHANNEL, user_id=chat)
        status = member.get("status")
        joined = status in ("creator", "administrator", "member")
        if status == "restricted":
            joined = member.get("is_member", False)
    except Exception:
        say(chat,
            "Üyelik kontrolü şu anda yapılamıyor. "
            "Biraz sonra /start yazarak tekrar deneyin.")
        return False

    if joined:
        return True

    categories.pop(chat, None)
    say(
        chat,
        "Haber veya kayıp ilanı göndermek için önce "
        "Sarıçamdanbihaber kanalımıza katılın.\n\n"
        "Kanala girip Katıl düğmesine basın. "
        "Sonra bota dönüp /start yazın.",
        reply_markup={
            "inline_keyboard": [[{
                "text": "📢 Kanala Katıl",
                "url": CHANNEL_URL
            }]]
        }
    )
    return False


def approval(query):
    if query["from"]["id"] != ADMIN:
        api("answerCallbackQuery",
            callback_query_id=query["id"],
            text="Bu işlem yöneticiye ait.")
        return

    api("answerCallbackQuery", callback_query_id=query["id"])
    action, source, message_id = query["data"].split(":")
    if action not in ("yes", "no"):
        return

    item = f"{source}:{message_id}"
    if db.execute(
        "SELECT 1 FROM decisions WHERE item=?", (item,)
    ).fetchone():
        say(ADMIN, "Bu gönderi daha önce işlendi.")
        return

    if action == "yes":
        db.execute(
            "INSERT INTO decisions VALUES (?, ?)",
            (item, "publishing")
        )
        db.commit()
        try:
            api("copyMessage",
                chat_id=CHANNEL,
                from_chat_id=int(source),
                message_id=int(message_id))
        except Exception:
            say(ADMIN,
                "Yayın doğrulanamadı. Kanalı kontrol edin. "
                "Bu gönderi otomatik tekrar yayımlanmayacak.")
            return
        status = "published"
        result = "✅ Kanalda yayımlandı."
    else:
        status = "rejected"
        result = "❌ Gönderi reddedildi."

    db.execute(
        "INSERT OR REPLACE INTO decisions VALUES (?, ?)",
        (item, status)
    )
    db.commit()
    api("editMessageText",
        chat_id=ADMIN,
        message_id=query["message"]["message_id"],
        text=result)


def handle(update):
    if "callback_query" in update:
        approval(update["callback_query"])
        return

    message = update.get("message")
    if not message:
        return
    if message["chat"]["type"] != "private":
        return

    chat = message["chat"]["id"]
    text = message.get("text", "")

    if text == "/kimlik":
        say(chat, f"Telegram kullanıcı numaran: {chat}")
        return

    if not membership_ok(chat):
        return

    if text in ("/start", "❌ İptal"):
        categories.pop(chat, None)
        say(chat,
            "Sarıçamdanbihaber'e hoş geldiniz!\n"
            "Haber veya kayıp ilanı göndermek için seçim yapın.\n"
            "Gönderiler yönetici onayından sonra yayımlanır.",
            reply_markup=MENU)
        return

    if text == "📢 Haber Kanalı":
        say(chat, CHANNEL_URL)
        return

    if text in ("📰 Haber Gönder", "🔎 Kayıp İlanı"):
        categories[chat] = text
        say(chat,
            "Mahalle, olay ve açıklamayı yazın.\n"
            "Fotoğraf veya videonun açıklamasını altına ekleyin.\n"
            "Kayıp ilanında yayımlanmasını istediğiniz "
            "iletişim bilgisini belirtin.\n"
            "Her mesaj ayrı incelenir; onaylanırsa kanalda yayımlanır.")
        return

    if not ADMIN:
        say(chat, "Yönetici kurulumu henüz tamamlanmadı.")
        return

    if chat not in categories:
        say(chat, "Önce Haber Gönder veya Kayıp İlanı seçin.",
            reply_markup=MENU)
        return

    if not any(k in message for k in ("text", "photo", "video")):
        say(chat, "Metin, fotoğraf veya video gönderin.")
        return

    message_id = message["message_id"]
    api("copyMessage",
        chat_id=ADMIN,
        from_chat_id=chat,
        message_id=message_id)

    user = message["from"]
    sender = user.get("username")
    sender = f"@{sender}" if sender else str(chat)

    say(
        ADMIN,
        f"{categories[chat]}\n"
        f"Gönderen: {user.get('first_name', '')} ({sender})\n"
        "Üstteki gönderiyi inceleyin.",
        reply_markup={
            "inline_keyboard": [[
                {
                    "text": "✅ Yayımla",
                    "callback_data": f"yes:{chat}:{message_id}"
                },
                {
                    "text": "❌ Reddet",
                    "callback_data": f"no:{chat}:{message_id}"
                }
            ]]
        }
    )
    say(chat, "✅ Gönderiniz yöneticiye iletildi.")


def main():
    api("deleteWebhook", drop_pending_updates=False)
    offset = 0
    print("Bot başlatıldı.", flush=True)

    while True:
        try:
            updates = api(
                "getUpdates",
                offset=offset,
                timeout=30,
                allowed_updates=["message", "callback_query"]
            )
            for update in updates:
                try:
                    handle(update)
                except Exception as error:
                    print(
                        "Gönderi hatası:",
                        type(error).__name__,
                        flush=True
                    )
                offset = update["update_id"] + 1
        except Exception as error:
            print(
                "Bağlantı hatası:",
                type(error).__name__,
                flush=True
            )
            time.sleep(5)


if __name__ == "__main__":
    main()

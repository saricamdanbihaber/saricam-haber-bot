import json
import os
import sqlite3
import time
import urllib.request

TOKEN = os.environ["BOT_TOKEN"]
ADMIN = int(os.environ.get("ADMIN_ID", "0"))
CHANNEL = "@saricamdanbihaber"
DB_PATH = os.environ.get("DB_PATH", "bot.db")

db = sqlite3.connect(DB_PATH)
db.execute(
    "CREATE TABLE IF NOT EXISTS decisions "
    "(item TEXT PRIMARY KEY, status TEXT)"
)
db.commit()

MENU = {
    "keyboard": [
        ["📰 Haber Gönder", "🔎 Kayıp İlanı"],
        ["📢 Haber Kanalı", "❌ İptal"]
    ],
    "resize_keyboard": True
}

categories = {}


def api(method, **data):
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{TOKEN}/{method}",
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        result = json.load(response)
    if not result.get("ok"):
        raise RuntimeError("Telegram işlemi tamamlanamadı.")
    return result["result"]


def say(chat, text, **extra):
    return api("sendMessage", chat_id=chat, text=text, **extra)


def handle(update):
    query = update.get("callback_query")
    if query:
        if query["from"]["id"] != ADMIN:
            api("answerCallbackQuery",
                callback_query_id=query["id"],
                text="Bu işlem yöneticiye ait.")
            return

        api("answerCallbackQuery", callback_query_id=query["id"])
        action, chat, message = query["data"].split(":")
        item = f"{chat}:{message}"

        if db.execute(
            "SELECT 1 FROM decisions WHERE item=?", (item,)
        ).fetchone():
            say(ADMIN, "Bu gönderi daha önce işlendi.")
            return

        if action == "yes":
            # Yayın sonucunun belirsiz kaldığı durumda tekrar yayımlamaz.
            db.execute(
                "INSERT INTO decisions VALUES (?, ?)",
                (item, "publishing")
            )
            db.commit()
            try:
                api("copyMessage", chat_id=CHANNEL,
                    from_chat_id=int(chat), message_id=int(message))
            except Exception:
                say(ADMIN,
                    "Yayın doğrulanamadı. Kanalı kontrol et; "
                    "bu gönderi otomatik olarak tekrar yayımlanmayacak.")
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
        return

    message = update.get("message")
    if not message or message["chat"]["type"] != "private":
        return

        chat = message["chat"]["id"]
    text = message.get("text", "")

    if chat != ADMIN and text != "/kimlik":
        try:
            member = api(
                "getChatMember",
                chat_id=CHANNEL,
                user_id=message["from"]["id"]
            )
            status = member["status"]
            joined = status in (
                "creator", "administrator", "member"
            ) or (
                status == "restricted"
                and member.get("is_member", False)
            )
        except Exception:
            say(chat,
                "Kanal üyeliğiniz şu anda kontrol edilemiyor. "
                "Lütfen biraz sonra /start yazarak tekrar deneyin.")
            return

        if not joined:
            categories.pop(chat, None)
            say(
                chat,
                "Haber veya kayıp ilanı göndermek için önce "
                "Sarıçamdanbihaber kanalımıza katılın.\n\n"
                "Aşağıdaki düğmeye basıp kanalda Katıl seçin. "
                "Ardından bu sohbete dönüp /start yazın.",
                reply_markup={
                    "inline_keyboard": [[{
                        "text": "📢 Kanala Katıl",
                        "url": "https://t.me/saricamdanbihaber"
                    }]]
                }
            )
            return

    if text == "/kimlik":
        say(chat, f"Telegram kullanıcı numaran: {chat}")
    elif text in ("/start", "❌ İptal"):
        categories.pop(chat, None)
        say(chat,
            "Sarıçamdanbihaber'e hoş geldiniz!\n"
            "Haber veya kayıp ilanı göndermek için seçim yapın.\n"
            "Gönderiler yönetici incelemesinden sonra yayımlanır.",
            reply_markup=MENU)
    elif text == "📢 Haber Kanalı":
        say(chat, "Haber kanalımız: https://t.me/saricamdanbihaber")
    elif text in ("📰 Haber Gönder", "🔎 Kayıp İlanı"):
        categories[chat] = text
        say(chat,
            "Mahalle, olay ve açıklamayı yazın. "
            "Fotoğraf veya videonuz varsa açıklamasını ekleyerek gönderin.\n"
            "Kayıp ilanında yayımlanmasını istediğiniz iletişim "
            "bilgisini belirtin.\n"
            "Her mesaj ayrı ayrı incelenir. "
            "Gönderdikleriniz onaylanırsa kanalda paylaşılabilir.")
    elif not ADMIN:
        say(chat, "Botun yönetici kurulumu henüz tamamlanmadı.")
    elif chat not in categories:
        say(chat, "Önce menüden Haber Gönder veya Kayıp İlanı seçin.",
            reply_markup=MENU)
    elif any(key in message for key in ("text", "photo", "video")):
        user = message["from"]
        name = user.get("first_name", "")
        username = user.get("username")
        sender = f"@{username}" if username else str(chat)

        api("copyMessage", chat_id=ADMIN,
            from_chat_id=chat, message_id=message["message_id"])
        buttons = {
            "inline_keyboard": [[
                {"text": "✅ Yayımla",
                 "callback_data": f"yes:{chat}:{message['message_id']}"},
                {"text": "❌ Reddet",
                 "callback_data": f"no:{chat}:{message['message_id']}"}
            ]]
        }
        say(ADMIN,
            f"{categories[chat]}\nGönderen: {name} ({sender})\n"
            "Üstteki gönderiyi inceleyin. "
            "Yayımla düğmesi içeriği doğrudan kanala gönderir.",
            reply_markup=buttons)
        say(chat, "✅ Gönderiniz yöneticiye iletildi.")
    else:
        say(chat, "Metin, fotoğraf veya video gönderin.")


def main():
    api("deleteWebhook", drop_pending_updates=False)
    offset = 0
    print("Bot başlatıldı.", flush=True)

    while True:
        try:
            updates = api(
                "getUpdates", offset=offset, timeout=30,
                allowed_updates=["message", "callback_query"]
            )
            for update in updates:
                try:
                    handle(update)
                except Exception:
                    print("Bir gönderi işlenemedi.", flush=True)
                offset = update["update_id"] + 1
        except Exception:
            print("Bağlantı yeniden deneniyor.", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()

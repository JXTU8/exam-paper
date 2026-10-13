import hashlib
import hmac
import logging
import os
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("exam-paper-collector")

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = FastAPI(title="Exam Paper Collector")


def configured() -> bool:
    return bool(BOT_TOKEN and CHANNEL_ID and WEBHOOK_SECRET)


def is_pdf(document: dict[str, Any]) -> bool:
    filename = str(document.get("file_name", "")).lower()
    mime_type = str(document.get("mime_type", "")).lower()
    return filename.endswith(".pdf") or mime_type == "application/pdf"


def secret_matches(provided: str | None) -> bool:
    return bool(
        WEBHOOK_SECRET
        and provided
        and hmac.compare_digest(provided.encode(), WEBHOOK_SECRET.encode())
    )


async def telegram(method: str, payload: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.post(f"{TELEGRAM_API}/{method}", json=payload)
    response.raise_for_status()
    body = response.json()
    if not body.get("ok"):
        raise RuntimeError(body.get("description", "Telegram API request failed"))
    return body


async def reply(chat_id: int, text: str) -> None:
    await telegram("sendMessage", {"chat_id": chat_id, "text": text})


@app.get("/")
async def home() -> dict[str, str]:
    return {"service": "exam-paper-collector", "status": "ok"}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, bool]:
    if not configured():
        logger.error("Bot is not configured")
        raise HTTPException(status_code=503, detail="Bot is not configured")
    if not secret_matches(x_telegram_bot_api_secret_token):
        raise HTTPException(status_code=403, detail="Invalid webhook secret")

    update = await request.json()
    message = update.get("message")
    if not message:
        return {"ok": True}

    chat_id = message.get("chat", {}).get("id")
    if not chat_id:
        return {"ok": True}
    # The collection channel is output-only: never post acknowledgements there.
    if str(chat_id) == str(CHANNEL_ID):
        return {"ok": True}

    document = message.get("document")
    if not document or not is_pdf(document):
        if message.get("text", "").strip().lower() in {"/start", "/help"}:
            await reply(
                chat_id,
                "Send an exam paper as a PDF document and I will submit it to the channel. "
                "You can send as many PDFs as you need.",
            )
            return {"ok": True}
        await reply(chat_id, "Please send an exam paper as a PDF document.")
        return {"ok": True}

    try:
        # Copies inside Telegram: no download, disk, database, or third-party file storage is needed.
        await telegram(
            "copyMessage",
            {
                "chat_id": CHANNEL_ID,
                "from_chat_id": chat_id,
                "message_id": message["message_id"],
            },
        )
        await reply(
            chat_id,
            "Received — your PDF has been submitted. Have another exam paper? "
            "Send the next PDF anytime. Use /start for instructions.",
        )
    except Exception:
        logger.exception("Could not copy PDF to the channel")
        await reply(chat_id, "Sorry, the submission could not be sent. Please try again shortly.")
    return {"ok": True}

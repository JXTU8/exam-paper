import hmac
import logging
import os
import threading

import requests
from flask import Flask, jsonify, request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("exam-paper-collector")

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = Flask(__name__)
pending_papers = {}
pending_lock = threading.Lock()


def configured():
    return bool(BOT_TOKEN and CHANNEL_ID and WEBHOOK_SECRET)


def is_pdf(document):
    filename = str(document.get("file_name", "")).lower()
    mime_type = str(document.get("mime_type", "")).lower()
    return filename.endswith(".pdf") or mime_type == "application/pdf"


def is_valid_label(label):
    return label.upper().startswith("KM")


def secret_matches(provided):
    return bool(
        WEBHOOK_SECRET
        and provided
        and hmac.compare_digest(provided.encode(), WEBHOOK_SECRET.encode())
    )


def telegram(method, payload):
    response = requests.post(f"{TELEGRAM_API}/{method}", json=payload, timeout=25)
    response.raise_for_status()
    body = response.json()
    if not body.get("ok"):
        raise RuntimeError(body.get("description", "Telegram API request failed"))
    return body


def reply(chat_id, text, reply_to_message_id=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id
    telegram("sendMessage", payload)


def submit_paper(document, label):
    payload = {"chat_id": CHANNEL_ID, "document": document["file_id"]}
    if label:
        payload["caption"] = label
    telegram("sendDocument", payload)


def submit_without_label(paper_key):
    with pending_lock:
        paper = pending_papers.pop(paper_key, None)
    if not paper:
        return
    try:
        submit_paper(paper["document"], "")
        logger.info("Sent unlabelled paper after one-minute timeout")
    except Exception:
        logger.exception("Could not send unlabelled PDF to the channel")


@app.get("/")
@app.get("/health")
def health():
    return jsonify(service="exam-paper-collector", status="ok")


@app.post("/webhook")
def webhook():
    if not configured():
        logger.error("Bot is not configured")
        return jsonify(ok=False, error="Bot is not configured"), 503

    header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if not secret_matches(header_secret):
        return jsonify(ok=False, error="Invalid webhook secret"), 403

    update = request.get_json(silent=True) or {}
    message = update.get("message")
    if not message:
        return jsonify(ok=True)

    chat_id = message.get("chat", {}).get("id")
    if not chat_id or str(chat_id) == str(CHANNEL_ID):
        return jsonify(ok=True)

    document = message.get("document")
    if document and is_pdf(document):
        caption_label = message.get("caption", "").strip()
        if is_valid_label(caption_label):
            try:
                submit_paper(document, caption_label)
                reply(
                    chat_id,
                    "Received — your PDF has been submitted. Have another exam paper? Send the next PDF anytime.",
                )
            except Exception:
                logger.exception("Could not send labelled PDF to the channel")
                reply(chat_id, "Sorry, the submission could not be sent. Please try again shortly and report to admin if the problem persists.")
            return jsonify(ok=True)

        paper_key = (chat_id, message["message_id"])
        timer = threading.Timer(60, submit_without_label, args=(paper_key,))
        timer.daemon = True
        with pending_lock:
            pending_papers[paper_key] = {"document": document, "timer": timer}
        timer.start()
        reply(
            chat_id,
            "What paper is this? Reply directly to the PDF with its label, for example: KMS Chem. "
            "You can also send future PDFs with a caption starting with <b>KM</b>.",
            message["message_id"],
        )
        return jsonify(ok=True)

    replied_message = message.get("reply_to_message", {})
    replied_document = replied_message.get("document")
    label = message.get("text", "").strip()
    if replied_document and is_pdf(replied_document):
        if not label:
            reply(chat_id, "Please reply to the PDF with a label, for example: KMS Chem")
            return jsonify(ok=True)
        if not is_valid_label(label):
            reply(
                chat_id,
                "What paper is this? Please reply directly to the PDF with a label starting with <b>KM</b>, "
                "for example: KMS Cs",
            )
            return jsonify(ok=True)
        paper_key = (chat_id, replied_message["message_id"])
        with pending_lock:
            paper = pending_papers.pop(paper_key, None)
        if not paper:
            reply(chat_id, "That PDF was already submitted without a label.")
            return jsonify(ok=True)
        paper["timer"].cancel()
        try:
            submit_paper(replied_document, label)
            reply(
                chat_id,
                "Received your paper has been submitted. Have another paper? Send the next PDF anytime.",
            )
        except Exception:
            logger.exception("Could not send PDF to the channel")
            reply(chat_id, "Sorry, the submission could not be sent. Please try again shortly and report to admin if the problem persists.")
        return jsonify(ok=True)

    if not document or not is_pdf(document):
        if message.get("text", "").strip().lower() in {"/start", "/help"}:
            reply(
                chat_id,
                "Send an exam paper as a PDF. Then reply directly to the PDF with its label, "
                "for example: KMS Phy.",
            )
        else:
            reply(chat_id, "Please send a PDF first, then reply directly to it with a label like: KMS Bio.")
        return jsonify(ok=True)

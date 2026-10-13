# Exam Paper Collector Bot

Flask webhook bot: PDFs with a caption starting `KM` (such as `KMS Chem`) are posted
immediately. Other PDFs have a one-minute window for the user to reply directly with a
label; after that, the PDF is posted without one.

## Render environment variables

```text
BOT_TOKEN=
CHANNEL_ID=
WEBHOOK_SECRET=
```

## UptimeRobot

Create an HTTP(s) monitor for:

```text
https://YOUR-RENDER-SERVICE.onrender.com/health
```

The root URL works too:

```text
https://YOUR-RENDER-SERVICE.onrender.com/
```

## Telegram webhook

```text
https://api.telegram.org/botYOUR_BOT_TOKEN/setWebhook?url=https://YOUR-RENDER-SERVICE.onrender.com/webhook&secret_token=YOUR_WEBHOOK_SECRET
```

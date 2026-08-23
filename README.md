# Mail.ru to Telegram Bot

Пересылка новых писем из Mail.ru в Telegram-чат. Python, Aiogram 3, IMAP.

## Возможности

- Периодическая проверка непрочитанных писем
- Текст и упрощённый HTML (теги Telegram)
- Вложения
- Повтор при ошибке в основном цикле

## Требования

- Python 3.13 (на Debian 12 Bookworm системный 3.11 недостаточен — используйте `uv python install 3.13` или Docker)
- Включённый IMAP в Mail.ru и **пароль приложения**, не пароль ящика
- Telegram-бот в целевом чате/канале (для `CHAT_ID` вида `-100…` бот должен быть админом)

## Установка на Debian

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"

cd mailru-to-telegrambot
uv python install 3.13
uv sync
cp .env.example .env
chmod 600 .env
```

Заполните `.env`, затем:

```bash
uv run python -m app.main
```

В логе `Нет новых писем` — IMAP работает. Ошибка login — почта; ошибка Telegram API — токен или `CHAT_ID`.

### systemd (пример)

`/etc/systemd/system/mailru-telegram-bot.service`:

```ini
[Unit]
Description=Mail.ru to Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=bot
WorkingDirectory=/opt/mailru-to-telegrambot
ExecStart=/home/bot/.local/bin/uv run python -m app.main
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mailru-telegram-bot
```

## Docker

```bash
docker build -t mailru-telegram-bot .
docker run -d --name mailru-telegram-bot --env-file .env --restart unless-stopped mailru-telegram-bot
```

## Переменные окружения

См. `.env.example`. Исходящие порты: 993 (imap.mail.ru) и 443 (api.telegram.org).

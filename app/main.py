import asyncio
import imaplib
import email
from email.header import decode_header
from bs4 import BeautifulSoup, Comment
from aiogram import Bot
from aiogram.types import FSInputFile
import os
import logging
import tempfile
import chardet
import html
from app.config import settings

# Настройка логирования: INFO для наших логов, WARNING для внешних библиотек
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Заглушаем технические логи aiogram и http-клиентов
logging.getLogger("aiogram").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

bot = Bot(token=settings.BOT_TOKEN)

TELEGRAM_ALLOWED_TAGS = [
    "b",
    "strong",
    "i",
    "em",
    "u",
    "ins",
    "s",
    "strike",
    "del",
    "a",
    "code",
    "pre",
]
TELEGRAM_MESSAGE_LIMIT = 4096


def decode_payload(payload: bytes) -> str:
    detected = chardet.detect(payload).get("encoding") or "utf-8"
    try:
        return payload.decode(detected, errors="ignore")
    except (UnicodeDecodeError, LookupError):
        return payload.decode("utf-8", errors="ignore")


def sanitize_html_for_telegram(html_content: str) -> str:
    """Очищает HTML, оставляя только теги, поддерживаемые Telegram."""
    if not html_content:
        return ""

    soup = BeautifulSoup(html_content, "html.parser")

    for unwanted_tag in soup.find_all(["style", "script"]):
        unwanted_tag.decompose()

    comments = soup.find_all(string=lambda text: isinstance(text, Comment))
    for comment in comments:
        comment.extract()

    for br in soup.find_all("br"):
        br.replace_with("\n")

    for tag in soup.find_all(True):
        if tag.name not in TELEGRAM_ALLOWED_TAGS:
            tag.unwrap()
        else:
            if tag.name == "a":
                href = tag.get("href")
                tag.attrs = {}
                if href:
                    tag["href"] = href
            else:
                tag.attrs = {}

    return str(soup).strip()


def truncate_telegram_html(text: str, max_len: int) -> str:
    if max_len <= 0:
        return ""
    if len(text) <= max_len:
        return text

    cut = text[:max_len]
    last_lt = cut.rfind("<")
    last_gt = cut.rfind(">")
    if last_lt > last_gt:
        cut = cut[:last_lt]

    soup = BeautifulSoup(cut, "html.parser")
    result = str(soup).strip()
    if len(result) > max_len:
        result = result[:max_len]
    return result


def decode_email_header(header):
    """Декодирует заголовок письма из различных кодировок"""
    if not header:
        return "Неизвестно"
    try:
        decoded_list = decode_header(header)
        result = ""
        for content, encoding in decoded_list:
            if isinstance(content, bytes):
                try:
                    if not encoding:
                        encoding = chardet.detect(content)["encoding"] or "utf-8"
                    result += content.decode(encoding, errors="ignore")
                except (UnicodeDecodeError, LookupError):
                    result += content.decode("utf-8", errors="ignore")
            else:
                result += str(content)
        return result.strip()
    except Exception as e:
        logger.error(f"Ошибка при декодировании заголовка: {e}")
        return str(header)


def decode_email_subject(subject):
    return decode_email_header(subject)


def decode_email_from(from_addr):
    try:
        if "<" in from_addr and ">" in from_addr:
            name, addr = email.utils.parseaddr(from_addr)
            decoded_name = decode_email_header(name)
            return f"{decoded_name} <{addr}>"
        return decode_email_header(from_addr)
    except Exception as e:
        logger.error(f"Ошибка при декодировании адреса отправителя: {e}")
        return from_addr


def get_email_content(email_message):
    """
    Извлекает содержимое из письма. Приоритет у HTML.
    Возвращает кортеж (содержимое, тип_содержимого: 'HTML' или 'TEXT').
    """
    text_content = ""
    html_content = ""

    try:
        if email_message.is_multipart():
            for part in email_message.walk():
                content_type = part.get_content_type()
                if (
                    part.get_content_maintype() == "multipart"
                    or part.get("Content-Disposition")
                ):
                    continue

                payload = part.get_payload(decode=True)
                if not payload:
                    continue

                decoded_text = decode_payload(payload)

                if content_type == "text/plain":
                    text_content = decoded_text
                elif content_type == "text/html":
                    html_content = decoded_text
        else:
            payload = email_message.get_payload(decode=True)
            if payload:
                content_type = email_message.get_content_type()
                decoded_text = decode_payload(payload)

                if content_type == "text/html":
                    html_content = decoded_text
                else:
                    text_content = decoded_text

        if html_content:
            return (sanitize_html_for_telegram(html_content), "HTML")
        if text_content:
            return (text_content.strip(), "TEXT")

        return ("Нет текста в письме", "TEXT")
    except Exception as e:
        logger.error(f"Ошибка при извлечении текста письма: {e}")
        return ("Ошибка при извлечении текста письма", "TEXT")


def get_email_attachments(email_message):
    attachments = []
    try:
        for part in email_message.walk():
            if (
                part.get_content_maintype() == "multipart"
                or part.get("Content-Disposition") is None
            ):
                continue

            filename = part.get_filename()
            if filename:
                decoded_filename = decode_email_header(filename)
                payload = part.get_payload(decode=True)
                if payload:
                    attachments.append((decoded_filename, payload))
    except Exception as e:
        logger.error(f"Ошибка при получении вложений: {e}")
    return attachments


def connect_imap():
    imap = imaplib.IMAP4_SSL(settings.MAIL_SERVER)
    imap.login(settings.MAIL_USERNAME, settings.MAIL_PASSWORD)
    imap.select("INBOX")
    return imap


def fetch_unseen_nums(imap):
    _, message_numbers = imap.search(None, "UNSEEN")
    if not message_numbers or not message_numbers[0]:
        return []
    return message_numbers[0].split()


def fetch_email_bytes(imap, num):
    _, msg_data = imap.fetch(num, "(BODY.PEEK[])")
    if msg_data and isinstance(msg_data[0], tuple):
        return msg_data[0][1]
    return None


def mark_seen(imap, num):
    imap.store(num, "+FLAGS", "\\Seen")


async def check_new_emails():
    imap = None
    try:
        imap = await asyncio.to_thread(connect_imap)
        msg_nums = await asyncio.to_thread(fetch_unseen_nums, imap)

        # Если писем нет, ничего не пишем в лог
        if not msg_nums:
            return

        for num in msg_nums:
            try:
                msg_bytes = await asyncio.to_thread(fetch_email_bytes, imap, num)
                if not msg_bytes:
                    logger.error(f"Пустое или некорректное сообщение {num}")
                    continue

                email_message = email.message_from_bytes(msg_bytes)

                subject = decode_email_subject(
                    email_message.get("subject", "Без темы")
                )
                from_addr = decode_email_from(
                    email_message.get("from", "Неизвестный отправитель")
                )

                content_str, content_type = get_email_content(email_message)

                from_addr_safe = html.escape(from_addr)
                subject_safe = html.escape(subject)

                if content_type == "HTML":
                    content_body = content_str
                else:
                    content_body = html.escape(content_str)

                header_part = (
                    f"<b>От кого:</b> {from_addr_safe}\n"
                    f"<b>Тема:</b> {subject_safe}\n"
                )

                max_body_len = TELEGRAM_MESSAGE_LIMIT - len(header_part) - 1
                message_text = header_part + truncate_telegram_html(
                    content_body, max_body_len
                )

                await bot.send_message(
                    chat_id=settings.CHAT_ID,
                    text=message_text,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )

                attachments = get_email_attachments(email_message)
                for filename, file_data in attachments:
                    try:
                        if not file_data:
                            logger.warning(f"Пустое вложение {filename}")
                            continue

                        with tempfile.TemporaryDirectory() as temp_dir:
                            safe_filename = "".join(
                                c
                                for c in filename
                                if c.isalnum() or c in (" ", "-", "_", ".")
                            ) or "attachment"
                            file_path = os.path.join(temp_dir, safe_filename)

                            with open(file_path, "wb") as f:
                                f.write(file_data)

                            input_file = FSInputFile(
                                file_path, filename=safe_filename
                            )
                            await bot.send_document(
                                chat_id=settings.CHAT_ID,
                                document=input_file,
                                caption=f"Вложение: {html.escape(safe_filename)}",
                            )
                    except Exception as e:
                        logger.error(
                            f"Ошибка при отправке вложения {filename}: {e}"
                        )
                        try:
                            await bot.send_message(
                                chat_id=settings.CHAT_ID,
                                text=f"Ошибка при отправке вложения: {html.escape(filename)}",
                            )
                        except Exception:
                            pass

                # Помечаем как прочитанное только после успешной отправки
                await asyncio.to_thread(mark_seen, imap, num)
                
                # Логируем только факт успешной отправки
                logger.info(f"Отправлено письмо в Telegram | От: {from_addr} | Тема: {subject}")

            except Exception as e:
                logger.error(
                    f"Ошибка при обработке письма {num}: {e}", exc_info=True
                )
                continue
    except Exception as e:
        logger.error(f"Ошибка при проверке почты: {e}", exc_info=True)
    finally:
        if imap is None:
            return
        try:
            await asyncio.to_thread(imap.close)
        except Exception:
            pass
        try:
            await asyncio.to_thread(imap.logout)
        except Exception as e:
            logger.warning(f"Не удалось корректно закрыть IMAP соединение: {e}")


async def main():
    try:
        while True:
            try:
                await check_new_emails()
                await asyncio.sleep(settings.CHECK_INTERVAL)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Ошибка в основном цикле: {e}", exc_info=True)
                await asyncio.sleep(settings.RETRY_INTERVAL)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Остановка бота пользователем")
    except Exception as e:
        logger.error(f"Фатальная ошибка: {e}", exc_info=True)
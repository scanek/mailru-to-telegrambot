import sys
import re

with open("app/main.py", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Insert helper functions before check_new_emails
helpers = """
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
    imap.store(num, '+FLAGS', '\\\\Seen')

async def check_new_emails():"""

content = content.replace("async def check_new_emails():", helpers)

# 2. Replace the body of check_new_emails()
# We'll use a regex to replace everything from "async def check_new_emails():" up to "async def main():"
new_check_new_emails_body = """
    imap = None
    try:
        imap = await asyncio.to_thread(connect_imap)
        msg_nums = await asyncio.to_thread(fetch_unseen_nums, imap)

        if not msg_nums:
            logger.info("Нет новых писем")
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
                    f"<b>От кого:</b> {from_addr_safe}\\n"
                    f"<b>Тема:</b> {subject_safe}\\n"
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
                
                # Mark as seen only after successful send
                await asyncio.to_thread(mark_seen, imap, num)

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

"""

# Regex replacement: match from "async def check_new_emails():" up to "async def main():"
pattern = re.compile(r"async def check_new_emails\(\):.*?(?=async def main\(\):)", re.DOTALL)
match = pattern.search(content)

if match:
    new_content = content[:match.end()]
    
    # Actually wait, we already replaced "async def check_new_emails():" with helpers + "async def check_new_emails():"
    # So let's re-read and replace just the body.
    pass

# Simpler logic:
with open("app/main.py", "r", encoding="utf-8") as f:
    original = f.read()

pattern2 = re.compile(r"async def check_new_emails\(\):.*?(?=async def main\(\):)", re.DOTALL)

replacement = helpers + new_check_new_emails_body + "\\n\\n"
new_original = pattern2.sub(replacement, original)

with open("app/main.py", "w", encoding="utf-8") as f:
    f.write(new_original)

print("Patched app/main.py successfully!")

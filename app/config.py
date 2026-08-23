from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    MAIL_USERNAME: str = Field(..., description="Email username")
    MAIL_PASSWORD: str = Field(..., description="Email password")
    MAIL_SERVER: str = Field(..., description="IMAP server address")

    BOT_TOKEN: str = Field(..., description="Telegram bot token")
    CHAT_ID: str = Field(..., description="Telegram chat ID")

    CHECK_INTERVAL: int = Field(
        default=300, description="Interval between email checks in seconds"
    )
    RETRY_INTERVAL: int = Field(
        default=60,
        description="Interval between retries in case of error in seconds",
    )


settings = Settings()

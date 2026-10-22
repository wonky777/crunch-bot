import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    token: str
    channel: str            # @username канала
    admin_ids: frozenset    # кто может гасить коды (ты и кассиры)
    required_friends: int   # сколько друзей нужно позвать
    db_path: str
    instagram_url: str

    @property
    def channel_url(self) -> str:
        return f"https://t.me/{self.channel.lstrip('@')}"


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("Не задан BOT_TOKEN (см. .env.example)")
    admins = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}
    if not admins:
        raise SystemExit("Не задан ADMIN_IDS — кому-то же нужно сканировать коды")
    return Config(
        token=token,
        channel=os.getenv("CHANNEL", "@crunch_krd").strip(),
        admin_ids=frozenset(admins),
        required_friends=int(os.getenv("REQUIRED_FRIENDS", "4")),
        db_path=os.getenv("DB_PATH", "crunch.db"),
        instagram_url=os.getenv("INSTAGRAM_URL", "https://www.instagram.com/crunch.krd"),
    )

"""SQLite-слой. Все функции синхронные и атомарные: в одном event loop
они не прерываются, поэтому двойное нажатие «Готово» ничего не ломает."""
import secrets
import sqlite3
import time

ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # без 0/O/1/I/L — чтобы не путали на кассе


class DB:
    def __init__(self, path: str):
        self.c = sqlite3.connect(path, check_same_thread=False)
        self.c.row_factory = sqlite3.Row
        self.c.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS users(
                user_id INTEGER PRIMARY KEY,
                username TEXT, first_name TEXT,
                invite_link TEXT,
                created_at INTEGER);
            CREATE TABLE IF NOT EXISTS friends(
                friend_id INTEGER PRIMARY KEY,      -- один человек засчитывается только раз
                inviter_id INTEGER NOT NULL,
                joined_at INTEGER,
                reward_code TEXT);                  -- NULL = ещё не потрачен на награду
            CREATE INDEX IF NOT EXISTS ix_friends_inviter ON friends(inviter_id);
            CREATE TABLE IF NOT EXISTS rewards(
                code TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at INTEGER,
                redeemed_at INTEGER,
                redeemed_by INTEGER);
            CREATE INDEX IF NOT EXISTS ix_rewards_user ON rewards(user_id);
            """
        )

    # ---------- users ----------
    def upsert_user(self, user_id, username, first_name):
        self.c.execute(
            """INSERT INTO users(user_id, username, first_name, created_at) VALUES(?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name""",
            (user_id, username, first_name, int(time.time())),
        )
        self.c.commit()

    def get_user(self, user_id):
        return self.c.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()

    def get_invite_link(self, user_id):
        r = self.c.execute("SELECT invite_link FROM users WHERE user_id=?", (user_id,)).fetchone()
        return r["invite_link"] if r else None

    def set_invite_link(self, user_id, link):
        self.c.execute("UPDATE users SET invite_link=? WHERE user_id=?", (link, user_id))
        self.c.commit()

    def inviter_by_link(self, link):
        r = self.c.execute("SELECT user_id FROM users WHERE invite_link=?", (link,)).fetchone()
        return r["user_id"] if r else None

    # ---------- friends ----------
    def add_friend(self, friend_id, inviter_id) -> bool:
        if friend_id == inviter_id:
            return False
        cur = self.c.execute(
            "INSERT OR IGNORE INTO friends(friend_id, inviter_id, joined_at) VALUES(?,?,?)",
            (friend_id, inviter_id, int(time.time())),
        )
        self.c.commit()
        return cur.rowcount == 1

    def free_friends(self, inviter_id):
        """Друзья, ещё не «потраченные» на награду."""
        rows = self.c.execute(
            "SELECT friend_id FROM friends WHERE inviter_id=? AND reward_code IS NULL ORDER BY joined_at",
            (inviter_id,),
        ).fetchall()
        return [r["friend_id"] for r in rows]

    # ---------- rewards ----------
    def issue_reward(self, user_id, friend_ids):
        """Атомарно: помечает друзей потраченными и создаёт код. None — если кто-то уже занят."""
        for _ in range(10):
            code = "".join(secrets.choice(ALPHABET) for _ in range(6))
            if not self.c.execute("SELECT 1 FROM rewards WHERE code=?", (code,)).fetchone():
                break
        try:
            self.c.execute("BEGIN")
            self.c.execute(
                "INSERT INTO rewards(code, user_id, created_at) VALUES(?,?,?)",
                (code, user_id, int(time.time())),
            )
            n = 0
            for fid in friend_ids:
                n += self.c.execute(
                    "UPDATE friends SET reward_code=? WHERE friend_id=? AND inviter_id=? AND reward_code IS NULL",
                    (code, fid, user_id),
                ).rowcount
            if n != len(friend_ids):
                self.c.execute("ROLLBACK")
                return None
            self.c.execute("COMMIT")
            return code
        except Exception:
            self.c.execute("ROLLBACK")
            raise

    def get_reward(self, code):
        return self.c.execute(
            """SELECT r.*, u.username, u.first_name FROM rewards r
               LEFT JOIN users u ON u.user_id=r.user_id WHERE r.code=?""",
            (code,),
        ).fetchone()

    def user_rewards(self, user_id):
        return self.c.execute(
            "SELECT * FROM rewards WHERE user_id=? ORDER BY created_at DESC", (user_id,)
        ).fetchall()

    def redeem(self, code, admin_id) -> bool:
        cur = self.c.execute(
            "UPDATE rewards SET redeemed_at=?, redeemed_by=? WHERE code=? AND redeemed_at IS NULL",
            (int(time.time()), admin_id, code),
        )
        self.c.commit()
        return cur.rowcount == 1

    def stats(self):
        q = lambda s: self.c.execute(s).fetchone()[0]
        return {
            "users": q("SELECT COUNT(*) FROM users"),
            "friends": q("SELECT COUNT(*) FROM friends"),
            "issued": q("SELECT COUNT(*) FROM rewards"),
            "redeemed": q("SELECT COUNT(*) FROM rewards WHERE redeemed_at IS NOT NULL"),
        }

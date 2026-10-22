import asyncio
import html
import logging
from datetime import datetime
from urllib.parse import quote

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatMemberStatus, ParseMode
from aiogram.filters import ChatMemberUpdatedFilter, Command, CommandObject, JOIN_TRANSITION
from aiogram.types import (BufferedInputFile, CallbackQuery, ChatMemberUpdated,
                           InlineKeyboardButton, InlineKeyboardMarkup, Message)

from config import load_config
from db import DB
from qr_card import render_card

cfg = load_config()
db = DB(cfg.db_path)
router = Router()
log = logging.getLogger("crunch")

STATE = {"channel_id": None, "bot_username": None}
MEMBER_OK = {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}


# ───────────────────────── helpers ─────────────────────────
def friends_word(n: int) -> str:
    return "друга" if n == 1 else "друзей"


def friends_dat(n: int) -> str:
    return "другу" if n == 1 else "друзьям"


def bar(have: int, need: int) -> str:
    have = min(have, need)
    return "🍪" * have + "▫️" * (need - have)


def fmt_dt(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%d.%m %H:%M")


async def is_member(bot: Bot, user_id: int) -> bool:
    try:
        m = await bot.get_chat_member(STATE["channel_id"], user_id)
    except Exception as e:
        log.warning("get_chat_member(%s) failed: %s", user_id, e)
        return False
    return m.status in MEMBER_OK or (m.status == ChatMemberStatus.RESTRICTED and m.is_member)


def deep_link(code: str) -> str:
    return f"https://t.me/{STATE['bot_username']}?start=r_{code}"


def main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📣 Канал", url=cfg.channel_url),
         InlineKeyboardButton(text="📸 Instagram", url=cfg.instagram_url)],
        [InlineKeyboardButton(text="🔗 Моя ссылка", callback_data="link"),
         InlineKeyboardButton(text="👯 Мои друзья", callback_data="friends")],
        [InlineKeyboardButton(text="✅ Готово", callback_data="done")],
        [InlineKeyboardButton(text="🎟 Мои коды", callback_data="codes")],
    ])


def sub_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📣 Подписаться на канал", url=cfg.channel_url)],
        [InlineKeyboardButton(text="🔄 Я подписался(ась)", callback_data="menu")],
    ])


def welcome_text(name: str = "") -> str:
    n = cfg.required_friends
    hi = f"Привет, {html.escape(name)}! 🍪" if name else "Привет! 🍪"
    return (
        f"{hi}\n"
        "Это <b>CRUNCH!</b> — cookies &amp; coffee ☕\n\n"
        "Дарим <b>бесплатный CRUNCH</b> за подписку 💗\n\n"
        "Как забрать:\n"
        f"1️⃣ Подпишись на <a href='{cfg.channel_url}'>наш канал</a>\n"
        f"2️⃣ Нажми «🔗 Моя ссылка» и отправь её <b>{n} {friends_dat(n)}</b> — они тоже должны подписаться\n"
        "3️⃣ Жми «✅ Готово» — пришлю твой QR\n"
        "4️⃣ Покажи QR на кассе и хрусти 😋"
    )


# ───────────────────────── /start ─────────────────────────
@router.message(Command("start"))
async def cmd_start(m: Message, command: CommandObject, bot: Bot):
    u = m.from_user
    db.upsert_user(u.id, u.username, u.first_name)

    arg = command.args or ""
    if arg.startswith("r_"):                       # QR отсканирован камерой
        return await show_redeem(m, arg[2:].upper())

    await m.answer(welcome_text(u.first_name), reply_markup=main_kb(), disable_web_page_preview=True)


@router.callback_query(F.data == "menu")
async def cb_menu(c: CallbackQuery, bot: Bot):
    await c.answer()
    if not await is_member(bot, c.from_user.id):
        return await c.message.answer("Ой, подписки пока не видно 🙈 Подпишись на канал и нажми кнопку ещё раз",
                                      reply_markup=sub_kb())
    await c.message.answer("Отлично, ты в канале! 🎉 Дальше — зови друзей по своей ссылке 👇",
                           reply_markup=main_kb())


# ───────────────────────── реф-ссылка ─────────────────────────
@router.callback_query(F.data == "link")
async def cb_link(c: CallbackQuery, bot: Bot):
    await c.answer()
    uid = c.from_user.id
    if not await is_member(bot, uid):
        return await c.message.answer("Сначала подпишись на канал — потом выдам ссылку для друзей 💗",
                                      reply_markup=sub_kb())
    db.upsert_user(uid, c.from_user.username, c.from_user.first_name)
    link = db.get_invite_link(uid)
    if not link:
        inv = await bot.create_chat_invite_link(STATE["channel_id"], name=f"u{uid}")
        link = inv.invite_link
        db.set_invite_link(uid, link)

    n = cfg.required_friends
    share = f"https://t.me/share/url?url={quote(link)}&text={quote('CRUNCH! — бесплатный CRUNCH за подписку 🍪')}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Отправить друзьям", url=share)],
        [InlineKeyboardButton(text="👯 Мои друзья", callback_data="friends")],
    ])
    await c.message.answer(
        f"Вот твоя личная ссылка на канал 🔗\n<code>{link}</code>\n\n"
        f"Отправь её <b>{n} {friends_dat(n)}</b>. Друг должен зайти в канал именно по ней и остаться подписанным — "
        "тогда я его засчитаю 💗",
        reply_markup=kb, disable_web_page_preview=True,
    )


@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION))
async def on_join(ev: ChatMemberUpdated, bot: Bot):
    if ev.chat.id != STATE["channel_id"] or not ev.invite_link:
        return
    friend = ev.new_chat_member.user
    if friend.is_bot:
        return
    inviter = db.inviter_by_link(ev.invite_link.invite_link)
    if not inviter or not db.add_friend(friend.id, inviter):
        return
    have = len(db.free_friends(inviter))
    need = cfg.required_friends
    text = (f"🍪 +1 друг! {html.escape(friend.first_name or 'кто-то')} теперь в канале\n"
            f"{bar(have, need)}  {min(have, need)}/{need}")
    if have >= need:
        text += "\n\nВсё готово — жми «Готово» 👇"
    try:
        await bot.send_message(inviter, text, reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="✅ Готово", callback_data="done")]]))
    except Exception:
        pass


# ───────────────────────── прогресс и награда ─────────────────────────
async def valid_friends(bot: Bot, uid: int):
    """Друзья, которые всё ещё подписаны на канал."""
    ok = []
    for fid in db.free_friends(uid):
        if await is_member(bot, fid):
            ok.append(fid)
    return ok


@router.callback_query(F.data == "friends")
async def cb_friends(c: CallbackQuery, bot: Bot):
    await c.answer()
    need = cfg.required_friends
    have = len(await valid_friends(bot, c.from_user.id))
    left = max(need - have, 0)
    txt = f"{bar(have, need)}\nПриглашено и подписано: <b>{min(have, need)}/{need}</b>"
    txt += (f"\nОсталось позвать: {left} {friends_word(left)}" if left else "\nВсе в сборе — жми «Готово» 🎉")
    await c.message.answer(txt, reply_markup=main_kb())


@router.callback_query(F.data == "done")
async def cb_done(c: CallbackQuery, bot: Bot):
    await c.answer()
    uid, need = c.from_user.id, cfg.required_friends
    if not await is_member(bot, uid):
        return await c.message.answer("Сначала подпишись на канал 💗", reply_markup=sub_kb())

    friends = await valid_friends(bot, uid)
    if len(friends) < need:
        left = need - len(friends)
        return await c.message.answer(
            f"{bar(len(friends), need)}\nПока {len(friends)}/{need}. Позови ещё {left} {friends_word(left)} "
            "по своей ссылке — и возвращайся 🍪",
            reply_markup=main_kb())

    code = db.issue_reward(uid, friends[:need])
    if not code:
        return await c.message.answer("Упс, что-то пошло не так — нажми «Готово» ещё раз 🙈")
    await send_card(c.message, code, "🎉 <b>Держи свой CRUNCH!</b>\n"
                    "Покажи этот QR на кассе CRUNCH — и забирай.\n\n"
                    f"Код: <code>{code}</code>\n"
                    "Хочешь ещё? Позови новых друзей — выдам новый код 😉")


async def send_card(msg: Message, code: str, caption: str):
    png = render_card(code, deep_link(code))
    await msg.answer_photo(BufferedInputFile(png, f"crunch_{code}.png"), caption=caption)


@router.callback_query(F.data == "codes")
async def cb_codes(c: CallbackQuery):
    await c.answer()
    rows = db.user_rewards(c.from_user.id)
    if not rows:
        return await c.message.answer("Кодов пока нет. Собери друзей и жми «Готово» 🍪", reply_markup=main_kb())
    active = [r for r in rows if not r["redeemed_at"]]
    lines = [f"{'✅ Получен' if r['redeemed_at'] else '🎟 Ждёт тебя'} · <code>{r['code']}</code> · {fmt_dt(r['created_at'])}"
             for r in rows[:10]]
    await c.message.answer("Твои коды:\n" + "\n".join(lines))
    for r in active[:3]:
        await send_card(c.message, r["code"], f"Код <code>{r['code']}</code>")


# ───────────────────────── касса (админ) ─────────────────────────
def is_admin(uid: int) -> bool:
    return uid in cfg.admin_ids


async def show_redeem(m: Message, code: str):
    if not is_admin(m.from_user.id):
        return await m.answer("Этот QR нужно показать на кассе CRUNCH 🍪 Там его отсканируют и выдадут твой CRUNCH 💗")
    r = db.get_reward(code)
    if not r:
        return await m.answer(f"❌ Код <code>{html.escape(code)}</code> не найден")
    who = f"@{r['username']}" if r["username"] else html.escape(r["first_name"] or str(r["user_id"]))
    if r["redeemed_at"]:
        return await m.answer(f"⚠️ Код <code>{code}</code> уже использован\n{who} · {fmt_dt(r['redeemed_at'])}")
    await m.answer(
        f"✅ Код <code>{code}</code> настоящий\nКлиент: {who}\nВыдан: {fmt_dt(r['created_at'])}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🍪 Выдать CRUNCH", callback_data=f"redeem:{code}")]]))


@router.callback_query(F.data.startswith("redeem:"))
async def cb_redeem(c: CallbackQuery, bot: Bot):
    if not is_admin(c.from_user.id):
        return await c.answer("Только для кассы", show_alert=True)
    code = c.data.split(":", 1)[1]
    r = db.get_reward(code)
    if r and db.redeem(code, c.from_user.id):
        await c.message.edit_text(f"🍪 Выдано! Код <code>{code}</code> погашен ({fmt_dt(int(datetime.now().timestamp()))})")
        try:
            await bot.send_message(r["user_id"], "Приятного хруста! 🍪💗 Спасибо, что ты с CRUNCH!")
        except Exception:
            pass
    else:
        await c.message.edit_text(f"⚠️ Код <code>{code}</code> уже использован или не найден")
    await c.answer()


@router.message(Command("redeem"))
async def cmd_redeem(m: Message, command: CommandObject):
    if not is_admin(m.from_user.id):
        return
    if not command.args:
        return await m.answer("Формат: /redeem КОД")
    await show_redeem(m, command.args.strip().upper())


@router.message(Command("stats"))
async def cmd_stats(m: Message):
    if not is_admin(m.from_user.id):
        return
    s = db.stats()
    await m.answer(f"📊 <b>CRUNCH! бот</b>\nПользователей: {s['users']}\nДрузей засчитано: {s['friends']}\n"
                   f"Кодов выдано: {s['issued']}\nCRUNCH выдано на кассе: {s['redeemed']}")


@router.message(Command("id"))
async def cmd_id(m: Message):
    await m.answer(f"Твой id: <code>{m.from_user.id}</code>")


# ───────────────────────── запуск ─────────────────────────
async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    bot = Bot(cfg.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    me = await bot.get_me()
    STATE["bot_username"] = me.username
    ch = await bot.get_chat(cfg.channel)
    STATE["channel_id"] = ch.id
    member = await bot.get_chat_member(ch.id, me.id)
    if member.status != ChatMemberStatus.ADMINISTRATOR:
        raise SystemExit(f"Бот должен быть администратором канала {cfg.channel} (право «Приглашать пользователей»)")
    log.info("@%s запущен, канал %s (%s), нужно друзей: %s", me.username, cfg.channel, ch.id, cfg.required_friends)

    dp = Dispatcher()
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=False)
    await dp.start_polling(bot, allowed_updates=["message", "callback_query", "chat_member"])


if __name__ == "__main__":
    asyncio.run(main())
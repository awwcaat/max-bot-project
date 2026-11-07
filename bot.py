import asyncio
import html
import threading
import traceback
from maxapi import Bot, Dispatcher, F
from maxapi.enums.chat_type import ChatType
from maxapi.filters.command import Command
from maxapi.enums.parse_mode import ParseMode
from maxapi.types import BotStarted, CallbackButton, LinkButton, MessageCallback, MessageCreated
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
import logic
import web


# ================================================================ НАСТРОЙКИб ПЕРЕМЕННЫЕ
TOKEN = "токен"
CURATOR_CODE = "1234"
WEB_PORT = 8080
web.CURATOR_CODE = CURATOR_CODE
bot = Bot(TOKEN)
dp = Dispatcher()
loop = None

MENU = [
    [("🙋 Мне нужна помощь", "need")],
    [("🤝 Хочу помочь", "give")],
    [("📋 Мои заявки", "my"), ("🎓 Мои занятия", "lessons")],
    [("ℹ️ Помощь", "help")],
]

HELP_TEXT = ("<b>ℹ️ Помощь</b>\n"
             "Здесь школьники помогают друг другу с учёбой.\n\n"
             "🙋 Мне нужна помощь — создайте заявку: выберите предмет и напишите тему.\n"
             "🤝 Хочу помочь — посмотрите заявки и возьмите одну. "
             f"Одновременно можно вести не больше {logic.MAX_ACTIVE} занятий. "
             "Подписка на предмет включает уведомления о новых заявках.\n"
             "📋 Мои заявки — ваши заявки; пока их никто не взял, их можно отменить.\n"
             "🎓 Мои занятия — начать и закончить занятие, поставить оценку, посмотреть свои часы.\n\n"
             "После занятия оба участника ставят оценку, а куратор проверяет и подтверждает часы наставника.")

FULL_TEXT = (f"У вас уже {logic.MAX_ACTIVE} активных занятия — это максимум.\n"
             "Закончите одно из них, и можно будет брать новые.")
FULL_BUTTONS = [[("🎓 Мои занятия", "lessons")], [("⬅️ Меню", "start")]]


# ================================================================ КОМАНДЫЫ
def keyboard(buttons):
    kb = InlineKeyboardBuilder()
    for row in buttons:
        max_row = []
        for label, command in row:
            if command.startswith("https://"):
                max_row.append(LinkButton(text=label, url=command))
            else:
                max_row.append(CallbackButton(text=label, payload=command))
        kb.row(*max_row)
    return [kb.as_markup()]


async def send(user_id, text, buttons=None, html_text=False):
    attachments = keyboard(buttons) if buttons else None
    text_format = ParseMode.HTML if html_text else None
    try:
        await bot.send_message(user_id=user_id, text=text, attachments=attachments, format=text_format)
    except Exception:
        traceback.print_exc()


async def send_curators(text):
    """Сигнал всем кураторам."""
    for curator_id in logic.curators():
        await send(curator_id, text, [[("🛡 Кабинет куратора", "cabinet")]], html_text=True)


def reject_note(r):
    text = (f"❌ Куратор не подтвердил занятие №{r['id']} ({r['subject']}: {r['topic']}). "
            f"Часы не засчитаны.\nКомментарий куратора: {r['curator_comment']}")
    asyncio.run_coroutine_threadsafe(send(r["nastavnik_id"], text, MENU), loop)


def menu_for(user_id):
    if logic.is_curator(user_id):
        return MENU[:-1] + [[("🛡 Кабинет куратора", "cabinet")]] + MENU[-1:]
    return MENU


async def pressed(event, keep_waiting=False):
    try:
        await event.ack(notification="✓")
    except Exception:
        traceback.print_exc()
    user = event.callback.user
    logic.get_user(user.user_id, user.first_name)
    if not keep_waiting:
        logic.set_waiting(user.user_id, None)
    return user.user_id


def num(event, position=1):
    return int(event.callback.payload.split()[position])


def safe(text):
    return html.escape(str(text))


def link(user_id):
    return f'<a href="max://user/{user_id}">{html.escape(logic.name_of(user_id))}</a>'


def slots_text(nastavnik_id):
    n = logic.active_count(nastavnik_id)
    text = f"Принято заявок: {n}/{logic.MAX_ACTIVE}."
    if n >= logic.MAX_ACTIVE:
        text += " Новые заявки вам пока не приходят — вернутся, когда закончите одно из занятий."
    return text


def sub_buttons(nastavnik_id, subject):
    if logic.is_sub(nastavnik_id, subject):
        return [(f"🔕 Отписаться от «{subject}»", f"unsub {subject}")]
    return [(f"🔔 Подписаться на «{subject}»", f"sub {subject}")]


def card(r, nastavnik_id):
    text = (f"<b>📌 Заявка №{r['id']}</b>\nПредмет: {r['subject']}\nТема: {safe(r['topic'])}\n"
            f"Ученик: {safe(logic.name_of(r['student_id']))}")
    if r["comment"]:
        text += f"\nКомментарий: {safe(r['comment'])}"
    buttons = [[("✅ Помогу", f"take {r['id']}"), ("➡️ Следующая", f"browse {r['subject']} {r['id']}")],
               sub_buttons(nastavnik_id, r["subject"]),
               [("⬅️ Меню", "start")]]
    return text, buttons


def stars(r):
    return [[(f"⭐{n}", f"stars {r['id']} {n}") for n in range(1, 6)]]


# ==================================================================== ГЛ МЕНЮ
@dp.bot_started()
async def start_button(event: BotStarted):
    user_id = event.user.user_id
    logic.get_user(user_id, event.user.first_name)
    await send(user_id, f"<b>🤝 Привет, {safe(event.user.first_name)}! Здесь школьники помогают друг другу "
                        "с учёбой.</b>\n"
                        "Что хотите сделать?", menu_for(user_id), html_text=True)


@dp.message_created(Command("start"))
async def start_command(event: MessageCreated):
    user_id = event.message.sender.user_id
    logic.get_user(user_id, event.message.sender.first_name)
    logic.set_waiting(user_id, None)
    await send(user_id, f"<b>🤝 Привет, {safe(event.message.sender.first_name)}! Здесь школьники помогают друг другу "
                        "с учёбой.</b>\n"
                        "Что хотите сделать?", menu_for(user_id), html_text=True)


@dp.message_callback(F.callback.payload == "start")
async def back_menu(event: MessageCallback):
    user_id = await pressed(event)
    await send(user_id, "Что хотите сделать?", menu_for(user_id), html_text=True)


@dp.message_created(Command("help"))
async def help_command(event: MessageCreated):
    user_id = event.message.sender.user_id
    logic.get_user(user_id, event.message.sender.first_name)
    logic.set_waiting(user_id, None)
    await send(user_id, HELP_TEXT, [[("⬅️ Меню", "start")]], html_text=True)


@dp.message_callback(F.callback.payload == "help")
async def help_button(event: MessageCallback):
    user_id = await pressed(event)
    await send(user_id, HELP_TEXT, [[("⬅️ Меню", "start")]], html_text=True)


# =========================================================================== УЧЕНИК
@dp.message_callback(F.callback.payload == "need")
async def on_need(event: MessageCallback):
    user_id = await pressed(event)
    try:
        logic.check_can_ask(user_id)
    except ValueError as error:
        await send(user_id, "⚠️ " + str(error), MENU, html_text=True)
        return
    buttons = [[(s.capitalize(), "ask " + s)] for s in logic.SUBJECTS]
    buttons.append([("⬅️ Назад", "start")])
    await send(user_id, "По какому предмету нужна помощь?", buttons, html_text=True)


@dp.message_callback(F.callback.payload.startswith("ask "))
async def on_ask(event: MessageCallback):
    user_id = await pressed(event)
    subject = event.callback.payload.split()[1]
    logic.set_waiting(user_id, ["topic", subject])
    await send(user_id, f"<b>{subject.capitalize()}. Напишите одним сообщением тему, с которой нужна "
                        "помощь.</b>\n" 
                        "Например: дроби", [[("✖️ Отмена", "start")]], html_text=True)


@dp.message_callback(F.callback.payload == "skipcomment")
async def on_skipcomment(event: MessageCallback):
    user_id = await pressed(event, keep_waiting=True)
    waiting = logic.data["users"][user_id]["waiting"]
    if waiting is None or waiting[0] != "comment":
        await send(user_id, "Что хотите сделать?", menu_for(user_id), html_text=True)
        return
    await make_request(user_id, waiting[1], waiting[2], None)


@dp.message_callback(F.callback.payload == "my")
async def my_requests(event: MessageCallback):
    user_id = await pressed(event)
    mine = logic.requests_of(user_id)
    if len(mine) == 0:
        await send(user_id, "Заявок пока нет.", MENU, html_text=True)
        return
    lines = []
    buttons = []
    for r in mine:
        line = f"№{r['id']} · {r['subject']}: {safe(r['topic'])} · {logic.STATUSES[r['status']]}"
        if r["status"] == "done":
            line = "✅ " + line
        if r["nastavnik_id"] is not None:
            line += f" (наставник: {safe(logic.name_of(r['nastavnik_id']))})"
        lines.append(line)
        if r["status"] == "open":
            buttons.append([(f"✖️ Отменить №{r['id']}", f"cancel {r['id']}")])
    buttons.append([("⬅️ Меню", "start")])
    await send(user_id, "Ваши заявки:\n" + "\n".join(lines), buttons, html_text=True)


@dp.message_callback(F.callback.payload.startswith("cancel "))
async def on_cancel(event: MessageCallback):
    user_id = await pressed(event)
    try:
        r = logic.cancel_request(user_id, num(event))
    except ValueError as error:
        await send(user_id, "⚠️ " + str(error), MENU)
        return
    await send(user_id, f"Заявка №{r['id']} отменена.", MENU, html_text=True)


# ==================================================================== НАСТАВНИК
@dp.message_callback(F.callback.payload == "give")
async def on_give(event: MessageCallback):
    user_id = await pressed(event)
    if logic.is_full(user_id):
        await send(user_id, FULL_TEXT, FULL_BUTTONS, html_text=True)
        return
    buttons = []
    for s in logic.SUBJECTS:
        label = s.capitalize()
        if logic.is_sub(user_id, s):
            label = "🔔 " + label
        buttons.append([(label, f"browse {s} 0")])
    buttons.append([("⬅️ Назад", "start")])
    await send(user_id, "По какому предмету вы готовы помочь?", buttons, html_text=True)


@dp.message_callback(F.callback.payload.startswith("browse "))
async def on_browse(event: MessageCallback):
    user_id = await pressed(event)
    if logic.is_full(user_id):
        await send(user_id, FULL_TEXT, FULL_BUTTONS, html_text=True)
        return
    subject = event.callback.payload.split()[1]
    after_id = num(event, 2)
    r = logic.next_request(subject, user_id, after_id)
    if r is None:
        text = f"По предмету «{subject}» сейчас заявок нет."
        if logic.is_sub(user_id, subject):
            text += "\nКак только появится новая — я пришлю её вам."
        else:
            text += "\nПодпишитесь, и я пришлю новую заявку, когда она появится."
        await send(user_id, text, [sub_buttons(user_id, subject), [("⬅️ Меню", "start")]], html_text=True)
    elif r["id"] == after_id:                            # по кругу вернулись к той же — она одна
        await send(user_id, "Других заявок по этому предмету пока нет.",
                   [sub_buttons(user_id, subject), [("⬅️ Меню", "start")]], html_text=True)
    else:
        text, buttons = card(r, user_id)
        await send(user_id, text, buttons, html_text=True)


# ====================================================================== ПОДПИСКИ
@dp.message_callback(F.callback.payload.startswith("sub "))
async def on_subscribe(event: MessageCallback):
    user_id = await pressed(event)
    subject = event.callback.payload.split()[1]
    try:
        logic.subscribe(user_id, subject)
    except ValueError as error:
        await send(user_id, "⚠️ " + str(error), MENU)
        return
    await send(user_id, f'Вы подписались на предмет: "{subject}"', [[("⬅️ Меню", "start")]])


@dp.message_callback(F.callback.payload.startswith("unsub "))
async def on_unsubscribe(event: MessageCallback):
    user_id = await pressed(event)
    subject = event.callback.payload.split()[1]
    logic.unsubscribe(user_id, subject)
    await send(user_id, f'Вы отписались от предмета: "{subject}"', [[("⬅️ Меню", "start")]])


@dp.message_callback(F.callback.payload.startswith("take "))
async def on_take(event: MessageCallback):
    user_id = await pressed(event)
    try:
        r = logic.take_request(user_id, num(event))
    except ValueError as error:
        await send(user_id, "⚠️ " + str(error), MENU, html_text=True)
        return
    begin = [[("▶️ Начать занятие", f"begin {r['id']}")], [("⬅️ Меню", "start")]]
    nastavnik_begin = [[("▶️ Начать занятие", f"begin {r['id']}")],
                       [("↩️ Отказаться от заявки", f"release {r['id']}")], [("⬅️ Меню", "start")]]
    topic = html.escape(r["topic"])
    note = ""
    if r["comment"]:
        note = f"Комментарий: {html.escape(r['comment'])}\n"
    await send(user_id, f"<b>Отлично! Заявка №{r['id']} ваша:</b> {r['subject']} — {topic}.\n{note}"
                        f"Ученик: {link(r['student_id'])} — нажмите на имя, чтобы написать "
                        "и договориться о звонке.\n"
                        "Когда начнёте занятие — нажмите «Начать занятие».\n"
                        f"{slots_text(user_id)}", nastavnik_begin, html_text=True)
    await send(r["student_id"], f"🎉 <b>Нашёлся наставник для заявки №{r['id']} "
                                f"({r['subject']} — {topic}):</b> {link(user_id)}.\n"
                                "Нажмите на имя, чтобы написать наставнику и договориться о звонке.\n"
                                "Когда начнёте занятие — нажмите «Начать занятие».", begin, html_text=True)


@dp.message_callback(F.callback.payload.startswith("release "))
async def on_release(event: MessageCallback):
    user_id = await pressed(event)
    try:
        r = logic.release_request(user_id, num(event))
    except ValueError as error:
        await send(user_id, "⚠️ " + str(error), MENU)
        return
    await send(user_id, f"<b>Вы отказались от заявки №{r['id']}</b>. {slots_text(user_id)}", MENU, html_text=True)
    await send_curators(f"⚠️ <b>Наставник {safe(logic.name_of(user_id))} отказался от заявки №{r['id']}</b> "
                        f"({r['subject']}: {safe(r['topic'])}, ученик {safe(logic.name_of(r['student_id']))}).")
    await send(r["student_id"], f"Наставник {safe(logic.name_of(user_id))} отказался от заявки №{r['id']} "
                                f"({r['subject']} — {safe(r['topic'])}). Она снова ждёт нового наставника.", MENU, html_text=True)
    for nastavnik_id in logic.nastavnik_for(r["subject"], r["student_id"]):
        if nastavnik_id != user_id:
            text, buttons = card(r, nastavnik_id)
            await send(nastavnik_id, "🔔 Заявка снова свободна!\n" + text, buttons, html_text=True)


# ==================================================== ЗАНЯТИЕ
@dp.message_callback(F.callback.payload == "lessons")
async def on_lessons(event: MessageCallback):
    user_id = await pressed(event)
    total, verified = logic.nastavnik_minutes(user_id)
    lines = [f"<b>⏱ Ваши часы наставника: {logic.show_minutes(total)} "
             f"(подтверждено куратором: {logic.show_minutes(verified)})</b>"]
    buttons = []
    for r in logic.lessons_of(user_id):
        role = "вы наставник" if r["nastavnik_id"] == user_id else "вы ученик"
        line = f"№{r['id']} · {r['subject']}: {safe(r['topic'])} · {role} · {logic.STATUSES[r['status']]}"
        if r["status"] == "done":
            line = "✅ " + line
        if r["nastavnik_id"] == user_id and r["credited"]:
            line += f" · куратор: {logic.CURATOR_STATUS[r['curator']]}"
        lines.append(line)
        if r["status"] == "taken":
            buttons.append([(f"▶️ Начать №{r['id']}", f"begin {r['id']}")])
            if r["nastavnik_id"] == user_id:
                buttons.append([(f"↩️ Отказаться №{r['id']}", f"release {r['id']}")])
        elif r["status"] == "started":
            buttons.append([(f"⏹ Закончить №{r['id']}", f"end {r['id']}")])
        elif r["status"] == "finished" and r["student_id"] == user_id:
            buttons += stars(r)
        elif r["status"] in ("finished", "done") and r["nastavnik_id"] == user_id and r["nastavnik_stars"] is None:
            buttons += stars(r)
    buttons.append([("⬅️ Меню", "start")])
    await send(user_id, "\n".join(lines), buttons, html_text=True)


@dp.message_callback(F.callback.payload.startswith("begin "))
async def on_begin(event: MessageCallback):
    user_id = await pressed(event)
    try:
        r = logic.start_lesson(user_id, num(event))
    except ValueError as error:
        await send(user_id, "⚠️ " + str(error), MENU)
        return
    text = f"▶️ Занятие №{r['id']} началось. Время идёт. Когда закончите — нажмите «Закончить»."
    end = [[("⏹ Закончить занятие", f"end {r['id']}")]]
    await send(r["nastavnik_id"], text, end)
    await send(r["student_id"], text, end)


@dp.message_callback(F.callback.payload.startswith("end "))
async def on_end(event: MessageCallback):
    user_id = await pressed(event)
    try:
        r = logic.finish_lesson(user_id, num(event))
    except ValueError as error:
        await send(user_id, "⚠️ " + str(error), MENU)
        return
    length = logic.show_minutes(r["minutes"])
    freed = ""
    if logic.active_count(r["nastavnik_id"]) == logic.MAX_ACTIVE - 1:
        freed = "\n🔔 Освободилось место: новые заявки по вашим подпискам снова будут приходить."
    await send(r["student_id"], f"⏹ Занятие №{r['id']} закончилось ({length}). Как всё прошло?\n"
                                "Оценку увидит только куратор.",
               stars(r) + [[("❌ Занятия не было", f"nolesson {r['id']}")]])
    await send(r["nastavnik_id"], f"⏹ Занятие №{r['id']} закончилось ({length}). "
                               "Как вам общение с учеником?\nОценку увидит только куратор." + freed,
               stars(r) + [[("❌ Занятия не было", f"nolesson {r['id']}")]])


@dp.message_callback(F.callback.payload.startswith("stars "))
async def on_stars(event: MessageCallback):
    user_id = await pressed(event)
    try:
        r = logic.rate(user_id, num(event), num(event, 2))
    except ValueError as error:
        await send(user_id, "⚠️ " + str(error), MENU)
        return
    logic.set_waiting(user_id, ["review", r["id"]])
    await send(user_id, "<b>Спасибо за оценку! 🙌\nХотите добавить комментарий к занятию?</b> "
                        "Напишите его одним сообщением. Его увидит только куратор.",
               [[("⏭ Не нужно", "start")]], html_text=True)
    given = num(event, 2)

    if user_id == r["student_id"]:
        if r["credited"]:
            total = logic.show_minutes(logic.nastavnik_minutes(r["nastavnik_id"])[0])
            await send(r["nastavnik_id"], f"✅ {logic.name_of(user_id)} подтвердил(а) занятие №{r['id']}: "
                                       f"записано {logic.show_minutes(r['minutes'])}. Всего у вас: {total}.", MENU)
        else:
            await send(r["nastavnik_id"], f"Занятие №{r['id']} подтверждено, но не засчитано: "
                                       f"короче {logic.MIN_MINUTES} мин.", MENU)

    if given <= logic.LOW_STARS:
        who = "Ученик" if user_id == r["student_id"] else "Наставник"
        await send_curators(f"⚠️ {who} {safe(logic.name_of(user_id))} поставил(а) {given}⭐ за занятие "
                            f"№{r['id']} ({safe(logic.name_of(r['nastavnik_id']))} → "
                            f"{safe(logic.name_of(r['student_id']))}, {r['subject']}: {safe(r['topic'])}).")


@dp.message_callback(F.callback.payload.startswith("nolesson "))
async def on_nolesson(event: MessageCallback):
    user_id = await pressed(event)
    try:
        r = logic.no_lesson(user_id, num(event))
    except ValueError as error:
        await send(user_id, "⚠️ " + str(error), MENU)
        return
    if user_id == r["student_id"]:
        who = "Ученик"
        other_id = r["nastavnik_id"]
    else:
        who = "Наставник"
        other_id = r["student_id"]
    await send(user_id, f"Понял: занятие №{r['id']} не засчитано. Куратор посмотрит, что случилось.", MENU)
    await send(other_id, f"{who} отметил(а), что занятие №{r['id']} не состоялось. Часы не записаны.", MENU)
    await send_curators(f"⚠️ {who} {safe(logic.name_of(user_id))} отметил(а): занятие №{r['id']} "
                        f"({safe(logic.name_of(r['nastavnik_id']))} → {safe(logic.name_of(r['student_id']))}) "
                        f"не состоялось ({r['minutes']} мин по таймеру).")


# ================================================================== КУРАТОР
@dp.message_created(Command("curator"))
async def on_curator(event: MessageCreated):
    user_id = event.message.sender.user_id
    logic.get_user(user_id, event.message.sender.first_name)
    words = event.message.body.text.split()
    if len(words) < 2 or words[1] != CURATOR_CODE:
        await send(user_id, "Неверный код куратора.", MENU)
        return
    logic.make_curator(user_id)
    await send(user_id, "🛡 Вы куратор. Я буду присылать сюда сигналы: низкие оценки и занятия, "
                        "которых не было.\nКабинет — кнопкой в меню.", menu_for(user_id))


@dp.message_created(Command("uncurator"))
async def on_uncurator(event: MessageCreated):
    user_id = event.message.sender.user_id
    logic.get_user(user_id, event.message.sender.first_name)
    if not logic.is_curator(user_id):
        await send(user_id, "Вы и так не куратор.", menu_for(user_id))
        return
    logic.remove_curator(user_id)
    await send(user_id, "Режим куратора выключен. Включить снова: /curator и код.", menu_for(user_id))


@dp.message_callback(F.callback.payload == "cabinet")
async def on_cabinet(event: MessageCallback):
    user_id = await pressed(event)
    if not logic.is_curator(user_id):
        await send(user_id, "Это только для куратора.", MENU)
        return
    waiting = len([r for r in logic.lessons_all() if r["credited"] and r["curator"] == "pending"])
    await send(user_id, f"🛡 Кабинет куратора: http://localhost:{WEB_PORT}/?key={CURATOR_CODE}\n"
                        "(откройте в браузере на компьютере, где запущен бот)\n\n"
                        f"Ждут проверки часов: {waiting}\n"
                        f"Требуют внимания: {len(logic.attention())}\n"
                        f"Заявок ждут наставника: {len(logic.open_requests())}", menu_for(user_id))


# ============================================================ комменты
async def topic_comment(user_id, subject, text):
    try:
        topic = logic.check_topic(text)
    except ValueError as error:
        await send(user_id, "⚠️ " + str(error), [[("✖️ Отмена", "start")]])
        return
    logic.set_waiting(user_id, ["comment", subject, topic])
    await send(user_id, "<b>Хотите добавить комментарий для наставника?</b> Например, что именно не получается "
                        "или к какому сроку нужна помощь.\nНапишите его одним сообщением "
                        "или нажмите «Пропустить».",
               [[("⏭ Пропустить", "skipcomment")], [("✖️ Отмена", "start")]], html_text=True)


async def make_request(user_id, subject, topic, comment):
    try:
        r = logic.create_request(user_id, subject, topic, comment)
    except ValueError as error:
        await send(user_id, "⚠️ " + str(error), [[("✖️ Отмена", "start")]])
        return
    logic.set_waiting(user_id, None)        # заявка создана — больше ничего не ждём
    print("Новая заявка:", r)
    await send(user_id, f"<b>✅ Заявка №{r['id']} создана:</b> {r['subject']} — {safe(r['topic'])}.\n"
                        "Как только наставник откликнется, я напишу.", menu_for(user_id), html_text=True)
    for nastavnik_id in logic.nastavnik_for(r["subject"], user_id):
        text, buttons = card(r, nastavnik_id)
        await send(nastavnik_id, "🔔 Новая заявка!\n" + text, buttons, html_text=True)


async def review_comment(user_id, request_id, text):
    try:
        r = logic.add_review(user_id, request_id, text)
    except ValueError as error:
        await send(user_id, "⚠️ " + str(error), [[("⏭ Не нужно", "start")]])
        return
    logic.set_waiting(user_id, None)
    await send(user_id, "Комментарий сохранён, спасибо! 🙌", menu_for(user_id))
    if user_id == r["student_id"]:
        given = r["student_stars"]
    else:
        given = r["nastavnik_stars"]
    if given <= logic.LOW_STARS:
        await send_curators(f"💬 Комментарий от {safe(logic.name_of(user_id))} к занятию №{r['id']} "
                            f"({given}⭐): {safe(text.strip())}")


@dp.message_created()
async def on_text(event: MessageCreated):
    if event.message.recipient.chat_type != ChatType.DIALOG:
        return

    sender = event.message.sender
    user_id = sender.user_id
    user = logic.get_user(user_id, sender.first_name)
    waiting = user["waiting"]
    text = event.message.body.text or ""

    if waiting is None:
        await send(user_id, "Выберите действие кнопкой ниже.", menu_for(user_id))
    elif waiting[0] == "topic":
        await topic_comment(user_id, waiting[1], text)
    elif waiting[0] == "comment":
        await make_request(user_id, waiting[1], waiting[2], text)
    elif waiting[0] == "review":
        await review_comment(user_id, waiting[1], text)


# ========================================= мейн луп
async def main():
    global loop
    loop = asyncio.get_running_loop()
    web.reject_note = reject_note
    threading.Thread(target=web.run, args=(WEB_PORT,), daemon=True).start()
    print(f"Кабинет куратора: http://localhost:{WEB_PORT}/?key={CURATOR_CODE}")
    print("Бот запущен. Остановить: красный квадрат в PyCharm")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

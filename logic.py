import json
import os
import threading
import time

FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")

lock = threading.Lock()

# ======================================================= ПЕРЕМЕННЫЕ
SUBJECTS = ["математика", "русский", "физика"]
MAX_OPEN = 3
MAX_TOPIC = 100
MAX_COMMENT = 300
MIN_MINUTES = 1
HANG_HOURS = 24
LOW_STARS = 2
MAX_ACTIVE = 3
ACTIVE_STATUSES = ("taken", "started")
CURATOR_STATUS = {"pending": "ждёт проверки", "verified": "подтверждено", "rejected": "отклонено"}

STATUSES = {
    "open": "ждёт наставника",
    "taken": "наставник найден",
    "started": "идёт занятие",
    "finished": "ждёт оценки ученика",
    "done": "занятие подтверждено",
    "no_lesson": "занятия не было",
    "cancelled": "отменена",
    "deleted": "удалена куратором",
}


# ======================================================================================= сохранение
def load():
    if not os.path.exists(FILE):
        return {"users": {}, "requests": []}
    with open(FILE, encoding="utf-8") as f:
        loaded = json.load(f)
    loaded["users"] = {int(user_id): user for user_id, user in loaded["users"].items()}
    return loaded


def save():
    with lock:
        temp = FILE + ".tmp"
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp, FILE)


data = load()


# ================================================================================ пользователи
def get_user(user_id, name):
    if user_id not in data["users"]:
        data["users"][user_id] = {"name": name, "waiting": None, "subjects": [], "is_curator": False}
        save()
    user = data["users"][user_id]
    if user["name"] != name:
        user["name"] = name
        save()
    return user


def set_waiting(user_id, value):
    user = data["users"][user_id]
    if user["waiting"] != value:
        user["waiting"] = value
        save()


def name_of(user_id):
    return data["users"][user_id]["name"]


def find_request(request_id):
    for r in data["requests"]:
        if r["id"] == request_id:
            return r
    raise ValueError("Заявка не найдена.")


# ======================================================================= ученик
def count(student_id):
    count = 0
    for r in data["requests"]:
        if r["student_id"] == student_id and r["status"] == "open":
            count += 1
    return count


def check_can_ask(student_id):
    if count(student_id) >= MAX_OPEN:
        raise ValueError(f"У вас уже {MAX_OPEN} заявки ждут наставника — это максимум.\n"
                         "Дождитесь ответа или отмените одну в «Мои заявки».")


def check_topic(topic):
    topic = topic.strip()
    if topic == "" or len(topic) > MAX_TOPIC:
        raise ValueError(f"Напишите тему короче, до {MAX_TOPIC} символов.")
    return topic


def check_comment(text):
    text = text.strip()
    if text == "" or len(text) > MAX_COMMENT:
        raise ValueError(f"Комментарий должен быть не пустым и не длиннее {MAX_COMMENT} символов.")
    return text


def create_request(student_id, subject, topic, comment=None):
    topic = check_topic(topic)
    if comment is not None:
        comment = check_comment(comment)
    check_can_ask(student_id)
    request = {
        "id": len(data["requests"]) + 1,
        "student_id": student_id,
        "subject": subject,
        "topic": topic,
        "comment": comment,
        "status": "open",
        "nastavnik_id": None,
        "created_at": time.time(),
        "started_at": None,
        "minutes": None,
        "student_stars": None,
        "nastavnik_stars": None,
        "student_review": None,
        "nastavnik_review": None,
        "credited": False,
        "curator": "pending",
        "curator_comment": None,
    }
    data["requests"].append(request)
    save()
    return request


def cancel_request(student_id, request_id):
    r = find_request(request_id)
    if r["student_id"] != student_id:
        raise ValueError("Это не ваша заявка.")
    if r["status"] != "open":
        raise ValueError("Эту заявку уже нельзя отменить: " + STATUSES[r["status"]] + ".")
    r["status"] = "cancelled"
    save()
    return r


def requests_of(student_id):
    mine = []
    for r in data["requests"]:
        if r["student_id"] == student_id and r["status"] != "cancelled":
            mine.append(r)
    return mine


# ===================================================================== наставник
def subjects_of(nastavnik_id):
    return list(data["users"][nastavnik_id]["subjects"])


def is_sub(nastavnik_id, subject):
    return subject in data["users"][nastavnik_id]["subjects"]


def subscribe(nastavnik_id, subject):
    if subject not in SUBJECTS:
        raise ValueError("Такого предмета нет.")
    user = data["users"][nastavnik_id]
    if subject not in user["subjects"]:
        user["subjects"].append(subject)
        save()


def unsubscribe(nastavnik_id, subject):
    user = data["users"][nastavnik_id]
    if subject in user["subjects"]:
        user["subjects"].remove(subject)
        save()


def active_count(nastavnik_id):
    count = 0
    for r in data["requests"]:
        if r["nastavnik_id"] == nastavnik_id and r["status"] in ACTIVE_STATUSES:
            count += 1
    return count


def is_full(nastavnik_id):
    return active_count(nastavnik_id) >= MAX_ACTIVE


def nastavnik_for(subject, student_id):
    found = []
    for user_id, user in data["users"].items():
        if subject in user["subjects"] and user_id != student_id and not is_full(user_id):
            found.append(user_id)
    return found


def next_request(subject, nastavnik_id, after_id=0):
    suitable = []
    for r in data["requests"]:
        if r["subject"] == subject and r["status"] == "open" and r["student_id"] != nastavnik_id:
            suitable.append(r)
    if len(suitable) == 0:
        return None
    for r in suitable:
        if r["id"] > after_id:
            return r
    return suitable[0]


def take_request(nastavnik_id, request_id):
    r = find_request(request_id)
    if r["student_id"] == nastavnik_id:
        raise ValueError("Нельзя взять свою заявку.")
    if r["status"] == "cancelled":
        raise ValueError("Ученик отменил эту заявку.")
    if r["status"] != "open":
        raise ValueError("Эту заявку уже взял другой наставник.")
    if is_full(nastavnik_id):
        raise ValueError(f"У вас уже {MAX_ACTIVE} активных занятия — это максимум.\n"
                         "Сначала проведите и закончите одно из них («Мои занятия»).")
    r["status"] = "taken"
    r["nastavnik_id"] = nastavnik_id
    save()
    return r


def release_request(nastavnik_id, request_id):
    r = find_request(request_id)
    if r["nastavnik_id"] != nastavnik_id:
        raise ValueError("Это не ваша заявка.")
    if r["status"] != "taken":
        raise ValueError("Отказаться можно только до начала занятия.")
    r["status"] = "open"
    r["nastavnik_id"] = None
    save()
    return r


# ========================================================================== занятие
def my_lesson(user_id, request_id):
    r = find_request(request_id)
    if user_id != r["student_id"] and user_id != r["nastavnik_id"]:
        raise ValueError("Это не ваше занятие.")
    return r


def start_lesson(user_id, request_id):
    r = my_lesson(user_id, request_id)
    if r["status"] != "taken":
        raise ValueError("Начать можно только занятие, которое ещё не начиналось.")
    r["status"] = "started"
    r["started_at"] = time.time()
    save()
    return r


def finish_lesson(user_id, request_id):
    r = my_lesson(user_id, request_id)
    if r["status"] != "started":
        raise ValueError("Это занятие не идёт.")
    r["status"] = "finished"
    r["minutes"] = int((time.time() - r["started_at"]) // 60)
    save()
    return r


def rate(user_id, request_id, stars):
    r = my_lesson(user_id, request_id)
    if stars < 1 or stars > 5:
        raise ValueError("Оценка — от 1 до 5.")
    if r["status"] not in ("finished", "done"):
        raise ValueError("Оценить можно только законченное занятие.")

    if user_id == r["student_id"]:
        if r["student_stars"] is not None or r["status"] != "finished":
            raise ValueError("Вы уже оценили это занятие.")
        r["student_stars"] = stars
        r["status"] = "done"
        r["credited"] = r["minutes"] >= MIN_MINUTES
    else:
        if r["nastavnik_stars"] is not None:
            raise ValueError("Вы уже оценили это занятие.")
        r["nastavnik_stars"] = stars
    save()
    return r


def add_review(user_id, request_id, text):
    r = my_lesson(user_id, request_id)
    text = check_comment(text)
    if user_id == r["student_id"]:
        field, stars = "student_review", r["student_stars"]
    else:
        field, stars = "nastavnik_review", r["nastavnik_stars"]
    if stars is None:
        raise ValueError("Сначала поставьте оценку занятию.")
    if r[field] is not None:
        raise ValueError("Вы уже оставили комментарий к этому занятию.")
    r[field] = text
    save()
    return r


def no_lesson(user_id, request_id):
    r = my_lesson(user_id, request_id)
    if r["status"] != "finished":
        raise ValueError("Это занятие уже подтверждено или ещё не закончено.")
    r["status"] = "no_lesson"
    r["credited"] = False
    save()
    return r


def lessons_of(user_id):
    mine = []
    for r in data["requests"]:
        if r["nastavnik_id"] is None:          # заявку никто не взял — это ещё не занятие
            continue
        if r["student_id"] == user_id or r["nastavnik_id"] == user_id:
            mine.append(r)
    return mine


def nastavnik_minutes(nastavnik_id):
    total = 0
    verified = 0
    for r in data["requests"]:
        if r["nastavnik_id"] == nastavnik_id and r["credited"] and r["curator"] != "rejected":
            total += r["minutes"]
            if r["curator"] == "verified":
                verified += r["minutes"]
    return total, verified


def show_minutes(minutes):
    if minutes >= 60:
        return f"{minutes // 60} ч {minutes % 60} мин"
    return f"{minutes} мин"


# ---------------------------------------------------------------- куратор
def make_curator(user_id):
    data["users"][user_id]["is_curator"] = True
    save()


def remove_curator(user_id):
    data["users"][user_id]["is_curator"] = False
    save()


def is_curator(user_id):
    user = data["users"].get(user_id)
    return user is not None and user["is_curator"]


def curators():
    return [uid for uid, user in data["users"].items() if user["is_curator"]]


def delete_request(request_id):
    r = find_request(request_id)
    if r["status"] != "open":
        raise ValueError("Удалить можно только заявку, которую ещё никто не взял.")
    r["status"] = "deleted"
    save()
    return r


def curator_verdict(request_id, verdict, comment=""):
    if verdict not in ("verified", "rejected"):
        raise ValueError("Решение: verified или rejected.")
    r = find_request(request_id)
    if r["status"] != "done" or not r["credited"]:
        raise ValueError("Проверять можно только засчитанное занятие.")
    if verdict == "rejected":
        r["curator_comment"] = check_comment(comment)
    r["curator"] = verdict
    save()
    return r


def hang_hours(r):
    return int((time.time() - r["created_at"]) // 3600)


def attention():
    found = []
    for r in data["requests"]:
        reasons = []
        if r["student_stars"] is not None and r["student_stars"] <= LOW_STARS:
            reasons.append(f"ученик поставил наставнику {r['student_stars']}⭐")
        if r["nastavnik_stars"] is not None and r["nastavnik_stars"] <= LOW_STARS:
            reasons.append(f"наставник поставил ученику {r['nastavnik_stars']}⭐")
        if r["status"] == "no_lesson":
            reasons.append("отмечено: занятия не было")
        if r["status"] == "open" and hang_hours(r) >= HANG_HOURS:
            reasons.append(f"заявка висит без наставника {hang_hours(r)} ч")
        if len(reasons) > 0:
            found.append((r, reasons))
    return found


def lessons_all():
    return [r for r in reversed(data["requests"]) if r["nastavnik_id"] is not None]


def open_requests():
    return [r for r in reversed(data["requests"]) if r["status"] == "open"]


def nastavnik_all():
    found = []
    for r in data["requests"]:
        if r["nastavnik_id"] is not None and r["nastavnik_id"] not in found:
            found.append(r["nastavnik_id"])
    return found

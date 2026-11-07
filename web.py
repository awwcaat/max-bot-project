import csv
import html
import io
import logging
import time
from flask import Flask, Response, redirect, request
import logic

# =============================================================== ПЕРЕМЕННЫЕ
CURATOR_CODE = ""
reject_note = None
app = Flask(__name__)

TABS = [("attention", "Внимание"), ("hours", "Часы"), ("requests", "Заявки"), ("totals", "Итоги")]
CURATOR_ICON = {"pending": "⏳", "verified": "✅", "rejected": "❌"}


# ---------------------------------------------------------------- функции
def esc(text):
    return html.escape(str(text))


def name(user_id):
    return esc(logic.name_of(user_id))


def check_key():
    return CURATOR_CODE != "" and request.values.get("key", "") == CURATOR_CODE


def button(key, tab, action, request_id, label, css, verdict=""):
    return (f'<form method="post" action="/{action}">'
            f'<input type="hidden" name="key" value="{esc(key)}">'
            f'<input type="hidden" name="tab" value="{tab}">'
            f'<input type="hidden" name="id" value="{request_id}">'
            f'<input type="hidden" name="verdict" value="{verdict}">'
            f'<button class="{css}">{label}</button></form>')


def reject_form(key, tab, request_id):
    return (f'<form method="post" action="/verdict" class="reject">'
            f'<input type="hidden" name="key" value="{esc(key)}">'
            f'<input type="hidden" name="tab" value="{tab}">'
            f'<input type="hidden" name="id" value="{request_id}">'
            f'<input type="hidden" name="verdict" value="rejected">'
            f'<input name="comment" maxlength="{logic.MAX_COMMENT}" placeholder="Причина отклонения" required>'
            f'<button class="no">✕ Отклонить</button></form>')


def notes(r):
    text = ""
    if r["comment"]:
        text += f'<div class="muted">💬 К заявке: {esc(r["comment"])}</div>'
    if r["student_review"]:
        text += f'<div class="muted">💬 Ученик о занятии: {esc(r["student_review"])}</div>'
    if r["nastavnik_review"]:
        text += f'<div class="muted">💬 Наставник о занятии: {esc(r["nastavnik_review"])}</div>'
    return text


def card(r, key, tab, reasons=None, warn=False):
    title = f"№{r['id']} · {esc(r['subject'].capitalize())} — {esc(r['topic'])}"
    if r["nastavnik_id"] is None:
        who = f"{name(r['student_id'])} · ждёт {logic.hang_hours(r)} ч"
    else:
        who = f"{name(r['nastavnik_id'])} → {name(r['student_id'])}"
        if r["minutes"] is not None:
            who += f" · {logic.show_minutes(r['minutes'])}"

    marks = ""
    if r["student_stars"] is not None or r["nastavnik_stars"] is not None:
        marks = (f'<div class="muted">⭐ от ученика {star(r["student_stars"])} · '
                 f'от наставника {star(r["nastavnik_stars"])}</div>')

    chips = ""
    for reason in reasons or []:
        chips += f'<span class="chip">{esc(reason)}</span>'
    if chips:
        chips = f'<div class="chips">{chips}</div>'

    actions = ""
    reject = ""
    if r["status"] == "open":
        actions = button(key, tab, "delete", r["id"], "Удалить заявку", "no")
    elif r["credited"] and r["curator"] == "pending":
        actions = button(key, tab, "verdict", r["id"], "✓ Засчитать", "ok", "verified")
        reject = reject_form(key, tab, r["id"])

    if actions:
        actions = f'<div class="actions">{actions}</div>'

    return (f'<div class="card{" warn" if warn else ""}">'
            f'<div class="title">{title}</div><div>{who}</div>{marks}{notes(r)}{chips}{actions}{reject}</div>')


def star(value):
    if value is None:
        return "—"
    if value <= logic.LOW_STARS:
        return f'<span class="chip">{value}</span>'
    return str(value)


def short_reasons(r):
    if r["status"] == "no_lesson":
        return ["занятия не было"]
    return []


STYLE = """
:root{--bg:#f4f3f9;--card:#fff;--text:#16151d;--muted:#6b6a78;--line:#e2e0ec;--warn:#fff4e2;--warnline:#efb15a;
 --chip:#ffe2b8;--ok:#237a37;--no:#b3261e;--accent:#4b3fd1;--accentbg:#ebe9ff}
@media (prefers-color-scheme:dark){:root{--bg:#121119;--card:#1c1b26;--text:#eee;--muted:#a3a1b3;--line:#2e2c3d;
 --warn:#2e240f;--warnline:#8a6022;--chip:#5a4214;--ok:#72c985;--no:#ff8a80;--accent:#b0a8ff;--accentbg:#2a2650}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:16px/1.4 Arial,sans-serif}
main{max-width:560px;margin:0 auto;padding:0 12px 24px}
header{position:sticky;top:0;z-index:1;background:var(--bg);padding:12px 0 8px}
h1{font-size:19px;margin:0 0 10px}
nav{display:grid;grid-template-columns:repeat(4,1fr);gap:4px;background:var(--card);border:1px solid var(--line);
 border-radius:12px;padding:4px}
nav a{text-align:center;padding:8px 2px;border-radius:9px;color:var(--muted);text-decoration:none;font-size:13px;line-height:1.25}
nav a.on{background:var(--accentbg);color:var(--accent);font-weight:bold}
nav b{display:block;font-size:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px;margin-top:10px}
.card.warn{background:var(--warn);border-color:var(--warnline)}
.title{font-weight:bold;margin-bottom:2px}
.muted{color:var(--muted);font-size:14px;margin-top:2px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.chip{background:var(--chip);border-radius:20px;padding:1px 9px;font-size:13px;color:var(--text);font-weight:bold}
.actions{display:flex;gap:8px;margin-top:10px}
.actions form{flex:1;margin:0}
button,.btn{width:100%;min-height:44px;font:inherit;font-size:15px;border-radius:10px;border:1px solid var(--line);
 background:var(--card);color:var(--text);cursor:pointer}
.reject{margin-top:8px}
input[name=comment]{width:100%;min-height:44px;font:inherit;font-size:15px;border-radius:10px;
 border:1px solid var(--line);background:var(--card);color:var(--text);padding:0 10px;margin-bottom:8px}
button.ok{border-color:var(--ok);color:var(--ok)} button.no{border-color:var(--no);color:var(--no)}
.btn{display:flex;align-items:center;justify-content:center;text-decoration:none;border-color:var(--accent);
 color:var(--accent);margin-top:14px}
.empty{color:var(--muted);text-align:center;padding:32px 0}
table{width:100%;border-collapse:collapse;background:var(--card);border-radius:12px;overflow:hidden;margin-top:10px}
th,td{text-align:left;padding:10px;border-bottom:1px solid var(--line)} th{color:var(--muted);font-weight:normal;font-size:14px}
h2{font-size:16px;margin:20px 0 0}
.row{display:flex;justify-content:space-between;gap:8px;padding:10px 12px;border-bottom:1px solid var(--line);font-size:14px}
.list{background:var(--card);border:1px solid var(--line);border-radius:12px;margin-top:10px;overflow:hidden}
"""


# ---------------------------------------------------------------- гл страница
@app.route("/")
def index():
    if not check_key():
        return "Нет доступа. Откройте кабинет по ссылке из бота (кнопка «Кабинет куратора»).", 403
    key = request.values["key"]
    attention = []
    for r, reasons in logic.attention():
        if r["status"] == "open" or (r["credited"] and r["curator"] == "pending") or r["status"] == "no_lesson":
            attention.append((r, reasons))

    attention_ids = [r["id"] for r, reasons in attention]

    hours = [r for r in logic.lessons_all()
             if r["credited"] and r["curator"] == "pending" and r["id"] not in attention_ids]

    requests = [r for r in logic.open_requests() if r["id"] not in attention_ids]

    tab = request.values.get("tab", "")
    if tab not in [t for t, label in TABS]:
        tab = "attention" if attention else "hours"
    counts = {"attention": len(attention), "hours": len(hours), "requests": len(requests), "totals": ""}

    if tab == "attention":
        content = "".join(card(r, key, tab, short_reasons(r), warn=True) for r, reasons in attention)
        empty = "Всё спокойно 👌"
    elif tab == "hours":
        content = "".join(card(r, key, tab) for r in hours)
        empty = "Нет часов на проверку"
    elif tab == "requests":
        content = "".join(card(r, key, tab) for r in requests)
        empty = "Все заявки разобраны"
    else:
        content = totals(key)
        empty = ""

    nav = ""
    for t, label in TABS:
        num = f"<b>{counts[t]}</b>" if counts[t] != "" else "<b>&nbsp;</b>"
        nav += f'<a href="/?key={esc(key)}&tab={t}" class="{"on" if t == tab else ""}">{num}{label}</a>'

    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Кабинет куратора</title><style>{STYLE}</style></head><body><main>
<header><h1>🛡 Кабинет куратора</h1><nav>{nav}</nav></header>
{content or f'<p class="empty">{empty}</p>'}
</main></body></html>"""


def totals(key):
    rows = ""
    for nastavnik_id in logic.nastavnik_all():
        total, verified = logic.nastavnik_minutes(nastavnik_id)
        rows += (f"<tr><td>{name(nastavnik_id)}</td><td>{logic.show_minutes(total)}</td>"
                 f"<td>{logic.show_minutes(verified)}</td></tr>")
    if rows == "":
        return ""
    history = ""
    for r in logic.lessons_all():
        icon = CURATOR_ICON[r["curator"]] if r["credited"] else "—"
        minutes = logic.show_minutes(r["minutes"]) if r["minutes"] is not None else esc(logic.STATUSES[r["status"]])
        history += (f'<div class="row"><span>№{r["id"]} {name(r["nastavnik_id"])} → {name(r["student_id"])}</span>'
                    f'<span>{minutes} {icon}</span></div>')
    return (f'<table><tr><th>Наставник</th><th>Записано</th><th>Засчитано вами</th></tr>{rows}</table>'
            f'<a class="btn" href="/export.csv?key={esc(key)}">Скачать часы (CSV)</a>'
            f'<h2>История занятий</h2><div class="list">{history}</div>'
            f'<p class="muted">✅ засчитано · ❌ отклонено · ⏳ ждёт вашего решения · — не засчитывалось</p>')


# ---------------------------------------------------------------- кнопки куратора
def back():
    return redirect(f"/?key={request.form['key']}&tab={request.form.get('tab', '')}", code=303)


@app.route("/verdict", methods=["POST"])
def verdict():
    if not check_key():
        return "Нет доступа.", 403
    try:
        r = logic.curator_verdict(int(request.form["id"]), request.form["verdict"],
                                  request.form.get("comment", ""))
    except (ValueError, KeyError) as error:
        return "Ошибка: " + esc(error), 400
    if r["curator"] == "rejected" and reject_note is not None:
        reject_note(r)
    return back()


@app.route("/delete", methods=["POST"])
def delete():
    if not check_key():
        return "Нет доступа.", 403
    try:
        logic.delete_request(int(request.form["id"]))
    except (ValueError, KeyError) as error:
        return "Ошибка: " + esc(error), 400
    return back()


# ---------------------------------------------------------------- выгрузка csv
@app.route("/export.csv")
def export_csv():
    if not check_key():
        return "Нет доступа.", 403
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";")
    writer.writerow(["Занятие", "Наставник", "Ученик", "Предмет", "Тема", "Минут", "Дата", "Куратор"])
    for r in logic.lessons_all():
        if r["credited"] and r["curator"] != "rejected":
            topic = r["topic"]
            if topic[:1] in ("=", "+", "-", "@"):
                topic = "'" + topic
            writer.writerow([r["id"], logic.name_of(r["nastavnik_id"]), logic.name_of(r["student_id"]),
                             r["subject"], topic, r["minutes"],
                             time.strftime("%d.%m.%Y", time.localtime(r["started_at"])),
                             logic.CURATOR_STATUS[r["curator"]]])
    return Response("﻿" + out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=hours.csv"})


# ---------------------------------------------------------------- апп ран
def run(port):
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
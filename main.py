import telebot
from telebot import types
import json
import sqlite3

with open('./settings/config.json', 'r') as f:
    config = json.load(f)

TOKEN = config['token']
ADMIN_ID = config['admin_id']

bot = telebot.TeleBot(TOKEN)

user_states = {}

def create_table():
    conn = sqlite3.connect('./base/reports.sql')
    cursor = conn.cursor()
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS reports
                      (report_id INTEGER PRIMARY KEY AUTOINCREMENT,
                       user_id INTEGER,
                       name TEXT,
                       text TEXT,
                       type TEXT,
                       status TEXT DEFAULT 'Новый ⌛')''')
    
    conn.commit()
    conn.close()

create_table()

@bot.message_handler(commands=['start'])
def start(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn_support = types.KeyboardButton('⭐ Техническая Поддержка')
    btn_bugtracker = types.KeyboardButton('📌 Баг-Трекер')
    markup.add(btn_support, btn_bugtracker)
    
    bot.send_message(message.chat.id,
                     '👋 Здравствуйте! Вас приветствует техническая поддержка Kohtop Dev.\n\nВыберите раздел:',
                     reply_markup=markup)

@bot.message_handler(content_types=['text'])
def handle_text(message):
    if message.text == '⭐ Техническая Поддержка':
        if message.from_user.id in user_states and user_states[message.from_user.id] == 'waiting_for_report':
            bot.send_message(message.chat.id, 'Вы уже в процессе ввода текста для тех. поддержки.')
        else:
            user_states[message.from_user.id] = 'waiting_for_report'
            msg = bot.reply_to(message, '✒ Введите текст, для отправки его в тех. поддержку.')
            bot.register_next_step_handler(msg, send_report)
    elif message.text == '📌 Баг-Трекер':
        show_bug_tracker(message.chat.id)

def show_bug_tracker(chat_id):
    reports = get_user_reports(chat_id)
    
    if not reports:
        bot.send_message(chat_id, "У вас пока нет репортов.")
        return
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for report in reports:
        btn = types.InlineKeyboardButton(f"Репорт #{report[0]} - {report[2]}", callback_data=f"report_info:{report[0]}")
        markup.add(btn)
    
    bot.send_message(chat_id, "Ваши заявки", reply_markup=markup)

def get_user_reports(user_id):
    conn = sqlite3.connect('./base/reports.sql')
    cursor = conn.cursor()
    
    cursor.execute('''SELECT report_id, text, status
                      FROM reports
                      WHERE user_id = ?
                      ORDER BY report_id DESC''', (user_id,))
    
    reports = cursor.fetchall()
    
    conn.close()
    return reports

def send_report(message):
    conn = sqlite3.connect('./base/reports.sql')
    cursor = conn.cursor()
    
    cursor.execute('INSERT INTO reports (user_id, name, text, type) VALUES (?, ?, ?, ?)',
                   (message.from_user.id, message.from_user.first_name, message.text, 'Техническая Поддержка'))
    
    report_id = cursor.lastrowid
    
    conn.commit()
    conn.close()
    
    bot.send_message(message.chat.id, 'Ваш репорт успешно отправлен!')
    
    notify_admin(report_id, message.from_user.id, message.from_user.first_name, message.text)

    user_states.pop(message.from_user.id, None)

def notify_admin(report_id, user_id, name, text):
    markup = types.InlineKeyboardMarkup()
    btn_accept = types.InlineKeyboardButton('Принять', callback_data=f'admin_action:accept:{report_id}')
    btn_decline = types.InlineKeyboardButton('Отклонить', callback_data=f'admin_action:decline:{report_id}')
    btn_reply = types.InlineKeyboardButton('Ответить', callback_data=f'admin_action:reply:{report_id}')
    markup.add(btn_accept, btn_decline, btn_reply)

    if isinstance(ADMIN_ID, list):
        for admin_id in ADMIN_ID:
            bot.send_message(admin_id,
                             f'Новый репорт #{report_id} от пользователя {name} (ID: {user_id})\n\n{text}',
                             reply_markup=markup)
    else:
        bot.send_message(ADMIN_ID,
                         f'Новый репорт #{report_id} от пользователя {name} (ID: {user_id})\n\n{text}',
                         reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    parts = call.data.split(':')
    
    if parts[0] == 'admin_action':
        action = parts[1]
        report_id = int(parts[2])
        
        current_status = check_report_status(report_id)

        if action == 'accept':
            if current_status == 'Новый ⌛':
                update_status(report_id, 'Одобрено')
                notify_user(get_user_id_by_report_id(report_id), report_id, 'Администратор рассмотрел ваш репорт. Статус: Одобрено')
                bot.answer_callback_query(call.id, f"Вы успешно одобрили репорт #{report_id}", show_alert=True)
            else:
                bot.answer_callback_query(call.id, "Этот репорт уже не новый.", show_alert=True)
        
        elif action == 'decline':
            if current_status == 'Новый ⌛':
                update_status(report_id, 'Отклонено')
                notify_user(get_user_id_by_report_id(report_id), report_id, 'Администратор рассмотрел ваш репорт. Статус: Отклонено')
                bot.answer_callback_query(call.id, f"Вы успешно отклонили репорт #{report_id}", show_alert=True)
            else:
                bot.answer_callback_query(call.id, "Этот репорт уже не новый.", show_alert=True)

        elif action == 'reply':
            msg = bot.reply_to(call.message, 'Введите текст ответа пользователю:')
            bot.register_next_step_handler(msg, lambda m: reply_user(m, report_id))
    
    elif parts[0] == 'report_info':
        report_id = int(parts[1])
        show_report_details(report_id, call.message.chat.id)

    else:
        bot.answer_callback_query(call.id, "Неизвестное действие.")

def reply_user(message, report_id):
    if check_report_status(report_id) != 'Новый ⌛':
        bot.reply_to(message, "Этот репорт уже рассмотрен.")
        return
    
    conn = sqlite3.connect('./base/reports.sql')
    cursor = conn.cursor()
    
    cursor.execute('SELECT user_id FROM reports WHERE report_id = ?', (report_id,))
    user_id = cursor.fetchone()[0]
    
    conn.close()
    
    bot.send_message(user_id,
                     f'Администратор ответил на ваш репорт\n\n📃 {message.text}')
    
    update_status(report_id, 'Рассмотрено')

def show_report_details(report_id, chat_id):
    conn = sqlite3.connect('./base/reports.sql')
    cursor = conn.cursor()
    
    cursor.execute('''SELECT text, status
                      FROM reports
                      WHERE report_id = ?''', (report_id,))
    
    report_info = cursor.fetchone()
    
    conn.close()
    
    if report_info:
        bot.send_message(chat_id, f"Репорт #{report_id}\nТекст: {report_info[0]}\nСтатус: {report_info[1]}")
    else:
        bot.send_message(chat_id, "Извините, репорт не найден.")

def check_report_status(report_id):
    conn = sqlite3.connect('./base/reports.sql')
    cursor = conn.cursor()
    
    cursor.execute('SELECT status FROM reports WHERE report_id = ?', (report_id,))
    status = cursor.fetchone()[0]
    
    conn.close()
    return status

def update_status(report_id, status):
    conn = sqlite3.connect('./base/reports.sql')
    cursor = conn.cursor()
    
    cursor.execute('UPDATE reports SET status = ? WHERE report_id = ?', (status, report_id))
    
    conn.commit()
    conn.close()

def get_user_id_by_report_id(report_id):
    conn = sqlite3.connect('./base/reports.sql')
    cursor = conn.cursor()
    
    cursor.execute('SELECT user_id FROM reports WHERE report_id = ?', (report_id,))
    user_id = cursor.fetchone()[0]
    
    conn.close()
    return user_id

def notify_user(user_id, report_id, message_text):
    bot.send_message(user_id, message_text)

if __name__ == '__main__':
    bot.polling()

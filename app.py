import os
import json
import time
import re
import sqlite3
import hashlib
import secrets
from datetime import datetime, timedelta, date
from functools import wraps
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, g
import requests
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(32))

# 配置
API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
API_BASE = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
AI_RATE_LIMIT = int(os.getenv("AI_RATE_LIMIT", "10"))
DB_PATH = os.path.join(os.path.dirname(__file__), "mindtask.db")


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            display_name TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            completed INTEGER DEFAULT 0,
            priority TEXT DEFAULT 'medium',
            scope TEXT DEFAULT 'today',
            due_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS invite_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            used_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            used_at TIMESTAMP,
            FOREIGN KEY (used_by) REFERENCES users(id)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS rate_limits (
            user_id INTEGER NOT NULL,
            endpoint TEXT NOT NULL,
            timestamp REAL NOT NULL
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_rate_user ON rate_limits(user_id, endpoint)")
    db.commit()

    cursor = db.execute("SELECT COUNT(*) FROM invite_codes WHERE used_by IS NULL")
    unused_count = cursor.fetchone()[0]
    if unused_count < 5:
        for _ in range(10):
            code = secrets.token_urlsafe(6)
            try:
                db.execute("INSERT INTO invite_codes (code) VALUES (?)", (code,))
            except sqlite3.IntegrityError:
                pass
        db.commit()
        cursor = db.execute("SELECT code FROM invite_codes WHERE used_by IS NULL")
        codes = [row[0] for row in cursor.fetchall()]
        print("=" * 50)
        print("📋 可用邀请码：")
        for c in codes:
            print(f"   {c}")
        print("=" * 50)
    
    db.close()


def hash_password(password):
    salt = secrets.token_hex(16)
    pwd_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
    return f"{salt}:{pwd_hash.hex()}"


def verify_password(stored_hash, password):
    try:
        salt, pwd_hash = stored_hash.split(':')
        check_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
        return check_hash.hex() == pwd_hash
    except Exception:
        return False


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({"error": "未登录", "code": 401}), 401
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated


def check_rate_limit(user_id, endpoint='ai', max_calls=None):
    if max_calls is None:
        max_calls = AI_RATE_LIMIT
    db = get_db()
    now = time.time()
    window_start = now - 60

    db.execute("DELETE FROM rate_limits WHERE timestamp < ?", (window_start,))

    cursor = db.execute(
        "SELECT COUNT(*) FROM rate_limits WHERE user_id = ? AND endpoint = ? AND timestamp > ?",
        (user_id, endpoint, window_start)
    )
    count = cursor.fetchone()[0]
    
    if count >= max_calls:
        return False

    db.execute(
        "INSERT INTO rate_limits (user_id, endpoint, timestamp) VALUES (?, ?, ?)",
        (user_id, endpoint, now)
    )
    db.commit()
    return True


def get_today():
    return date.today()

def get_week_range(d):
    sunday = d - timedelta(days=d.weekday() + 1) if d.weekday() != 6 else d
    saturday = sunday + timedelta(days=6)
    return sunday, saturday

def get_week_key(d):
    sunday, _ = get_week_range(d)
    return sunday.strftime("%Y-%m-%d")


def get_system_prompt():
    today = get_today()
    today_str = today.strftime("%Y-%m-%d")
    weekday_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    weekday = weekday_names[today.weekday()]
    
    sunday, saturday = get_week_range(today)
    
    return f"""你是 MindTask AI，一个"边聊天边整理待办"的智能助手。
用户会用自然语言和你聊天，内容可能很模糊，比如"这周要把简历改一下""今年想学英语""今天下午给客户回电话"。

你的核心能力是：从用户的话中提取出具体任务，并判断任务属于哪个时间维度。

今天是 {today_str}（{weekday}），本周范围是 {sunday.strftime("%Y-%m-%d")}（周日）到 {saturday.strftime("%Y-%m-%d")}（周六）。

## 时间维度判断规则
- "今天""下午""晚上""马上" → scope: "today", due_date: "{today_str}"
- "这周""周三""这个礼拜" → scope: "week", due_date: 对应具体日期
- "下周""下个礼拜""下周一" → scope: "week", due_date: 下周对应日期
- "这个月""月底""15号" → scope: "month", due_date: 当月对应日期
- "下个月""下月初" → scope: "month", due_date: 下个月对应日期  
- "今年""年底""暑假""过年前" → scope: "year", due_date: 今年内大致日期
- "明年""明年春天" → scope: "year", due_date: 明年对应大致日期
- 如果用户没说时间，根据任务性质判断：日常小事→today，一般任务→week，大目标→month/year

## 返回 JSON 格式（严格只返回 JSON，不要其他文字）

添加单个任务：
{{"action": "add", "tasks": [{{"title": "任务标题", "priority": "high/medium/low", "scope": "today/week/month/year", "due_date": "YYYY-MM-DD"}}]}}

添加多个任务（用户一句话可能包含多个任务）：
{{"action": "add", "tasks": [{{"title": "任务1", "priority": "medium", "scope": "today", "due_date": "YYYY-MM-DD"}}, {{"title": "任务2", "priority": "low", "scope": "week", "due_date": "YYYY-MM-DD"}}]}}

完成任务：{{"action": "complete", "task_id": 任务ID}}
删除任务：{{"action": "delete", "task_id": 任务ID}}
普通聊天：{{"action": "chat", "message": "你的友好回复"}}

## 任务标题规则
- 从用户模糊的话中提炼出简洁明确的任务标题
- "这周要把简历改一下" → "修改简历"
- "今年想学英语" → "学习英语"
- "今天下午记得给客户回电话" → "给客户回电话"
- "下个月要去体检" → "去体检"

注意：只返回 JSON，不要有其他文字。一句话中如果有多个任务要分别提取。"""


def call_ai(messages):
    if not API_KEY or API_KEY.strip() == "":
        return json.dumps({"action": "chat", "message": "请先配置 DEEPSEEK_API_KEY 环境变量"})

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 2048
    }

    try:
        response = requests.post(
            f"{API_BASE}/chat/completions",
            headers=headers,
            json=payload,
            timeout=60
        )
        result = response.json()
        return result["choices"][0]["message"]["content"]
    except Exception as e:
        return json.dumps({"action": "chat", "message": f"调用 AI 失败: {str(e)}"})


def parse_ai_response(ai_text):
    try:
        data = json.loads(ai_text.strip())
        return data
    except Exception:
        pass
    try:
        json_match = re.search(r'\{.*\}', ai_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except Exception:
        pass
    return {"action": "chat", "message": ai_text}


@app.route("/login")
def login_page():
    if 'user_id' in session:
        return redirect(url_for('index'))
    return render_template("login.html")


@app.route("/")
@login_required
def index():
    return render_template("index.html")


@app.route("/api/register", methods=["POST"])
def register():
    data = request.json
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    invite_code = (data.get("invite_code") or "").strip()
    display_name = (data.get("display_name") or username).strip()

    if not username or not password:
        return jsonify({"error": "用户名和密码不能为空"}), 400
    
    if len(username) < 3 or len(username) > 20:
        return jsonify({"error": "用户名长度 3-20 字符"}), 400
    
    if not re.match(r'^[a-zA-Z0-9_]+$', username):
        return jsonify({"error": "用户名只能包含字母、数字、下划线"}), 400

    if len(password) < 6:
        return jsonify({"error": "密码至少 6 位"}), 400

    if not invite_code:
        return jsonify({"error": "需要邀请码才能注册"}), 400

    db = get_db()

    code_row = db.execute(
        "SELECT id FROM invite_codes WHERE code = ? AND used_by IS NULL",
        (invite_code,)
    ).fetchone()
    
    if not code_row:
        return jsonify({"error": "邀请码无效或已被使用"}), 400

    existing = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if existing:
        return jsonify({"error": "用户名已被注册"}), 400

    pwd_hash = hash_password(password)
    cursor = db.execute(
        "INSERT INTO users (username, password_hash, display_name) VALUES (?, ?, ?)",
        (username, pwd_hash, display_name)
    )
    user_id = cursor.lastrowid

    db.execute(
        "UPDATE invite_codes SET used_by = ?, used_at = CURRENT_TIMESTAMP WHERE id = ?",
        (user_id, code_row['id'])
    )
    db.commit()

    session['user_id'] = user_id
    session['username'] = username
    session['display_name'] = display_name
    session.permanent = True
    app.permanent_session_lifetime = timedelta(days=30)

    return jsonify({"success": True, "username": username, "display_name": display_name})


@app.route("/api/login", methods=["POST"])
def login():
    data = request.json
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()

    if not username or not password:
        return jsonify({"error": "用户名和密码不能为空"}), 400

    db = get_db()
    user = db.execute(
        "SELECT id, username, password_hash, display_name FROM users WHERE username = ?",
        (username,)
    ).fetchone()

    if not user or not verify_password(user['password_hash'], password):
        return jsonify({"error": "用户名或密码错误"}), 401

    db.execute("UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?", (user['id'],))
    db.commit()

    session['user_id'] = user['id']
    session['username'] = user['username']
    session['display_name'] = user['display_name'] or user['username']
    session.permanent = True
    app.permanent_session_lifetime = timedelta(days=30)

    return jsonify({
        "success": True,
        "username": user['username'],
        "display_name": user['display_name'] or user['username']
    })


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True})


@app.route("/api/me")
@login_required
def get_me():
    return jsonify({
        "user_id": session['user_id'],
        "username": session['username'],
        "display_name": session.get('display_name', session['username'])
    })


@app.route("/api/tasks", methods=["GET"])
@login_required
def get_tasks():
    user_id = session['user_id']
    db = get_db()
    rows = db.execute(
        "SELECT id, title, completed, priority, scope, due_date, created_at FROM tasks WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,)
    ).fetchall()
    
    tasks = []
    for r in rows:
        tasks.append({
            "id": r['id'],
            "title": r['title'],
            "completed": bool(r['completed']),
            "priority": r['priority'],
            "scope": r['scope'],
            "due_date": r['due_date'],
            "created_at": r['created_at']
        })
    return jsonify(tasks)


@app.route("/api/tasks", methods=["POST"])
@login_required
def add_task():
    user_id = session['user_id']
    data = request.json
    today_str = get_today().strftime("%Y-%m-%d")
    
    db = get_db()
    cursor = db.execute(
        "INSERT INTO tasks (user_id, title, priority, scope, due_date) VALUES (?, ?, ?, ?, ?)",
        (user_id, data.get("title", ""), data.get("priority", "medium"),
         data.get("scope", "today"), data.get("due_date", today_str))
    )
    db.commit()
    
    task_id = cursor.lastrowid
    return jsonify({
        "id": task_id,
        "title": data.get("title", ""),
        "completed": False,
        "priority": data.get("priority", "medium"),
        "scope": data.get("scope", "today"),
        "due_date": data.get("due_date", today_str)
    })


@app.route("/api/tasks/<int:task_id>", methods=["PUT"])
@login_required
def update_task(task_id):
    user_id = session['user_id']
    data = request.json
    db = get_db()

    task = db.execute("SELECT id FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id)).fetchone()
    if not task:
        return jsonify({"error": "任务不存在"}), 404
    
    updates = []
    values = []
    for field in ["title", "completed", "priority", "scope", "due_date"]:
        if field in data:
            if field == "completed":
                updates.append(f"{field} = ?")
                values.append(1 if data[field] else 0)
            else:
                updates.append(f"{field} = ?")
                values.append(data[field])
    
    if updates:
        values.append(task_id)
        values.append(user_id)
        db.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id = ? AND user_id = ?", values)
        db.commit()
    
    return jsonify({"success": True})


@app.route("/api/tasks/<int:task_id>", methods=["DELETE"])
@login_required
def delete_task(task_id):
    user_id = session['user_id']
    db = get_db()
    db.execute("DELETE FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id))
    db.commit()
    return jsonify({"success": True})


@app.route("/api/chat", methods=["POST"])
@login_required
def chat():
    user_id = session['user_id']
    user_message = request.json.get("message", "").strip()

    if not user_message:
        return jsonify({"error": "消息不能为空"}), 400

    if not check_rate_limit(user_id, 'ai'):
        return jsonify({"reply": "⚠️ 操作太频繁了，请稍后再试（每分钟最多10次）", "timestamp": time.time()})

    db = get_db()

    rows = db.execute(
        "SELECT id, title, completed, priority, scope, due_date FROM tasks WHERE user_id = ?",
        (user_id,)
    ).fetchall()
    
    task_context = "\n".join([
        f"- [ID:{r['id']}] [{'✓' if r['completed'] else '○'}] {r['title']} (scope:{r['scope']}, due:{r['due_date']}, priority:{r['priority']})"
        for r in rows
    ]) or "暂无任务"
    
    system_prompt = get_system_prompt() + f"\n\n当前任务列表：\n{task_context}"
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message}
    ]
    
    ai_response = call_ai(messages)
    
    try:
        action_data = parse_ai_response(ai_response)
    except Exception:
        action_data = {"action": "chat", "message": ai_response}
    
    response_message = action_data.get("message", "")
    
    if action_data.get("action") == "add":
        added_tasks = []
        task_list = action_data.get("tasks", [])
        
        if not task_list and "title" in action_data:
            task_list = [action_data]
        
        today_str = get_today().strftime("%Y-%m-%d")
        
        for t in task_list:
            due = t.get("due_date", today_str)
            try:
                datetime.strptime(due, "%Y-%m-%d")
            except Exception:
                due = today_str
            
            cursor = db.execute(
                "INSERT INTO tasks (user_id, title, priority, scope, due_date) VALUES (?, ?, ?, ?, ?)",
                (user_id, t.get("title", ""), t.get("priority", "medium"),
                 t.get("scope", "today"), due)
            )
            added_tasks.append(t.get("title", ""))
        
        db.commit()
        
        if len(added_tasks) == 1:
            response_message = f"✅ 已添加任务：{added_tasks[0]}"
        else:
            task_names = "、".join(added_tasks)
            response_message = f"✅ 已添加 {len(added_tasks)} 个任务：{task_names}"
    
    elif action_data.get("action") == "complete":
        task_id = action_data.get("task_id")
        task_row = db.execute("SELECT title FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id)).fetchone()
        if task_row:
            db.execute("UPDATE tasks SET completed = 1 WHERE id = ? AND user_id = ?", (task_id, user_id))
            db.commit()
            response_message = f"✅ 已完成任务：{task_row['title']}"
    
    elif action_data.get("action") == "delete":
        task_id = action_data.get("task_id")
        task_row = db.execute("SELECT title FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id)).fetchone()
        if task_row:
            response_message = f"🗑️ 已删除任务：{task_row['title']}"
            db.execute("DELETE FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id))
            db.commit()
    
    elif action_data.get("action") == "chat":
        response_message = action_data.get("message", ai_response)

    return jsonify({
        "reply": response_message,
        "timestamp": time.time()
    })


@app.route("/api/admin/invite-codes", methods=["POST"])
@login_required
def generate_invite_codes():
    user_id = session['user_id']
    if user_id != 1:
        return jsonify({"error": "无权限"}), 403
    
    count = request.json.get("count", 5)
    count = min(count, 50)
    
    db = get_db()
    codes = []
    for _ in range(count):
        code = secrets.token_urlsafe(6)
        try:
            db.execute("INSERT INTO invite_codes (code) VALUES (?)", (code,))
            codes.append(code)
        except sqlite3.IntegrityError:
            pass
    db.commit()
    
    return jsonify({"codes": codes})


@app.route("/api/admin/invite-codes", methods=["GET"])
@login_required
def list_invite_codes():
    user_id = session['user_id']
    if user_id != 1:
        return jsonify({"error": "无权限"}), 403
    
    db = get_db()
    rows = db.execute("""
        SELECT ic.code, ic.used_at, u.username as used_by_name
        FROM invite_codes ic
        LEFT JOIN users u ON ic.used_by = u.id
        ORDER BY ic.created_at DESC
    """).fetchall()
    
    return jsonify([{
        "code": r['code'],
        "used_by": r['used_by_name'],
        "used_at": r['used_at']
    } for r in rows])


@app.route("/api/admin/migrate", methods=["POST"])
@login_required
def migrate_from_json():
    user_id = session['user_id']
    if user_id != 1:
        return jsonify({"error": "无权限"}), 403
    
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    if not os.path.exists(data_dir):
        return jsonify({"message": "没有找到旧数据目录"})
    
    db = get_db()
    migrated = 0
    
    for user_dir_name in os.listdir(data_dir):
        user_data_dir = os.path.join(data_dir, user_dir_name)
        tasks_file = os.path.join(user_data_dir, "tasks.json")
        
        if os.path.isdir(user_data_dir) and os.path.exists(tasks_file):
            with open(tasks_file, 'r', encoding='utf-8') as f:
                old_tasks = json.load(f)
            
            for t in old_tasks:
                db.execute(
                    "INSERT INTO tasks (user_id, title, completed, priority, scope, due_date, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (user_id, t.get('title', ''), 1 if t.get('completed') else 0,
                     t.get('priority', 'medium'), t.get('scope', 'today'),
                     t.get('due_date', ''), t.get('created_at', datetime.now().strftime("%Y-%m-%d %H:%M")))
                )
                migrated += 1
    
    db.commit()
    return jsonify({"message": f"已迁移 {migrated} 个任务到你的账号下"})


init_db()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)

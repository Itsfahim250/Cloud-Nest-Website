import json
import os
import uuid
import hashlib
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename

# ==========================================
#         CONFIGURATION
# ==========================================
PORT = int(os.environ.get("PORT", 8080))
app = Flask(__name__)
CORS(app)

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
DEV_DATA_FILE = os.path.join(DATA_DIR, "developers.json")
UPLOAD_FOLDER = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ==========================================
#         HELPER FUNCTIONS
# ==========================================
def load_devs():
    if os.path.exists(DEV_DATA_FILE):
        with open(DEV_DATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_devs(devs):
    with open(DEV_DATA_FILE, "w") as f:
        json.dump(devs, f, indent=4)

def generate_api_key(email):
    """Email থেকে deterministic API key তৈরি হয় - লগআউট/লগিনেও same key আসে"""
    return "cn_" + hashlib.sha256(email.encode()).hexdigest()[:32]

def get_dev_by_api_key(api_key):
    devs = load_devs()
    for email, info in devs.items():
        if info.get('api_key') == api_key:
            return email, info
    return None, None

def get_host_url():
    return os.environ.get("RENDER_EXTERNAL_URL", "http://127.0.0.1:8080").rstrip('/')

def format_bytes(b):
    if b < 1024: return f"{b} B"
    elif b < 1024**2: return f"{b/1024:.2f} KB"
    elif b < 1024**3: return f"{b/1024**2:.2f} MB"
    else: return f"{b/1024**3:.2f} GB"

# ==========================================
#         KEEP-ALIVE (Cron-job.org এ এই URL দাও)
# ==========================================
@app.route('/ping')
def ping():
    """cron-job.org এ এই /ping URL দিলে Render স্লিপ করবে না"""
    return jsonify({"status": "alive", "message": "☁️ CloudNest is running!"})

@app.route('/')
def home():
    return jsonify({"status": "ok", "service": "CloudNest API", "version": "2.0"})

# ==========================================
#         DEVELOPER AUTH
# ==========================================
@app.route('/api/dev/register', methods=['POST'])
def dev_register():
    data = request.json or {}
    name = data.get('name', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '').strip()

    if not name or not email or not password:
        return jsonify({"status": "error", "message": "সব ফিল্ড পূরণ করুন।"})

    devs = load_devs()
    if email in devs:
        return jsonify({"status": "error", "message": "এই ইমেইল আগেই রেজিস্টার্ড।"})

    api_key = generate_api_key(email)
    devs[email] = {"name": name, "email": email, "password": password, "api_key": api_key}
    save_devs(devs)
    return jsonify({"status": "success", "message": "রেজিস্ট্রেশন সফল!", "api_key": api_key, "name": name, "email": email})

@app.route('/api/dev/login', methods=['POST'])
def dev_login():
    data = request.json or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '').strip()

    devs = load_devs()
    if email in devs and devs[email]['password'] == password:
        info = devs[email]
        return jsonify({"status": "success", "api_key": info['api_key'], "name": info['name'], "email": email})
    return jsonify({"status": "error", "message": "ইমেইল বা পাসওয়ার্ড ভুল।"})

# ==========================================
#         REALTIME DATABASE API
# ==========================================
@app.route('/api/db', methods=['POST'])
def api_db():
    data = request.json or {}
    api_key = data.get('api_key')
    action = data.get('action')
    key = data.get('key', 'default')
    payload = data.get('data', '')

    user_id, dev_info = get_dev_by_api_key(api_key)
    if not user_id:
        return jsonify({"status": "error", "message": "Invalid API Key."})

    db_file = os.path.join(DATA_DIR, f"{api_key}_db.json")
    db_data = {}
    if os.path.exists(db_file):
        with open(db_file, "r") as f:
            db_data = json.load(f)

    if action == 'save':
        db_data[key] = payload
        with open(db_file, "w") as f: json.dump(db_data, f, indent=2)
        return jsonify({"status": "success", "message": "Data saved!"})

    elif action == 'load':
        return jsonify({"status": "success", "data": db_data.get(key, "")})

    elif action == 'all':
        return jsonify({"status": "success", "data": db_data})

    elif action == 'delete':
        if key in db_data:
            del db_data[key]
            with open(db_file, "w") as f: json.dump(db_data, f, indent=2)
        return jsonify({"status": "success", "message": "Deleted."})

    elif action == 'edit':
        new_data = data.get('new_data', '')
        db_data[key] = new_data
        with open(db_file, "w") as f: json.dump(db_data, f, indent=2)
        return jsonify({"status": "success", "message": "Updated."})

    return jsonify({"status": "error", "message": "Invalid action."})

# ==========================================
#         AUTHENTICATION API
# ==========================================
@app.route('/api/auth', methods=['POST'])
def api_auth():
    data = request.json or {}
    api_key = data.get('api_key')
    action = data.get('action')
    username = data.get('username', '')
    password = data.get('password', '')

    user_id, dev_info = get_dev_by_api_key(api_key)
    if not user_id:
        return jsonify({"status": "error", "message": "Invalid API Key."})

    auth_file = os.path.join(DATA_DIR, f"{api_key}_auth.json")
    auth_data = {}
    if os.path.exists(auth_file):
        with open(auth_file, "r") as f:
            auth_data = json.load(f)

    if action == 'register':
        if username in auth_data:
            return jsonify({"status": "error", "message": "User already exists!"})
        uid = str(uuid.uuid4())
        auth_data[username] = {"password": password, "uid": uid}
        with open(auth_file, "w") as f: json.dump(auth_data, f, indent=2)
        return jsonify({"status": "success", "message": "Registered!", "uid": uid})

    elif action == 'login':
        if username in auth_data and auth_data[username]['password'] == password:
            return jsonify({"status": "success", "message": "Logged in!", "uid": auth_data[username].get('uid', '')})
        return jsonify({"status": "error", "message": "Wrong credentials."})

    elif action == 'all':
        return jsonify({"status": "success", "data": auth_data})

    elif action == 'delete':
        if username in auth_data:
            del auth_data[username]
            with open(auth_file, "w") as f: json.dump(auth_data, f, indent=2)
        return jsonify({"status": "success", "message": "User deleted."})

    elif action == 'edit':
        new_password = data.get('new_password', '')
        if username in auth_data and new_password:
            auth_data[username]['password'] = new_password
            with open(auth_file, "w") as f: json.dump(auth_data, f, indent=2)
            return jsonify({"status": "success"})
        return jsonify({"status": "error", "message": "User not found."})

    return jsonify({"status": "error", "message": "Invalid action."})

# ==========================================
#         FILE STORAGE API
# ==========================================
@app.route('/api/upload', methods=['POST'])
def upload_file():
    api_key = request.form.get('api_key')
    user_id, dev_info = get_dev_by_api_key(api_key)
    if not user_id:
        return jsonify({"status": "error", "message": "Invalid API key"})

    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "No file uploaded"})
    file = request.files['file']
    if file.filename == '':
        return jsonify({"status": "error", "message": "Empty file"})

    filename = secure_filename(file.filename)
    unique_filename = f"{api_key}_{uuid.uuid4().hex[:8]}_{filename}"
    filepath = os.path.join(UPLOAD_FOLDER, unique_filename)
    file.save(filepath)
    size = os.path.getsize(filepath)
    file_url = f"{get_host_url()}/uploads/{unique_filename}"
    return jsonify({"status": "success", "url": file_url, "filename": unique_filename, "size": format_bytes(size)})

@app.route('/api/storage/list', methods=['POST'])
def list_files():
    data = request.json or {}
    api_key = data.get('api_key')
    user_id, _ = get_dev_by_api_key(api_key)
    if not user_id:
        return jsonify({"status": "error", "message": "Invalid API Key."})

    files = []
    for fname in os.listdir(UPLOAD_FOLDER):
        if fname.startswith(api_key + "_"):
            fpath = os.path.join(UPLOAD_FOLDER, fname)
            size = os.path.getsize(fpath)
            ext = fname.rsplit('.', 1)[-1].lower() if '.' in fname else 'file'
            files.append({
                "filename": fname,
                "display_name": fname.replace(f"{api_key}_", "", 1),
                "url": f"{get_host_url()}/uploads/{fname}",
                "size": size,
                "size_str": format_bytes(size),
                "ext": ext
            })
    return jsonify({"status": "success", "files": files})

@app.route('/api/storage/delete', methods=['POST'])
def delete_file_api():
    data = request.json or {}
    api_key = data.get('api_key')
    filename = data.get('filename', '')
    user_id, _ = get_dev_by_api_key(api_key)
    if not user_id:
        return jsonify({"status": "error", "message": "Invalid API Key."})
    if not filename.startswith(api_key + "_"):
        return jsonify({"status": "error", "message": "Unauthorized."})
    fpath = os.path.join(UPLOAD_FOLDER, filename)
    if os.path.exists(fpath):
        os.remove(fpath)
    return jsonify({"status": "success", "message": "File deleted."})

@app.route('/uploads/<filename>')
def serve_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

# ==========================================
#         USAGE API
# ==========================================
@app.route('/api/usage', methods=['POST'])
def usage():
    data = request.json or {}
    api_key = data.get('api_key')
    user_id, _ = get_dev_by_api_key(api_key)
    if not user_id:
        return jsonify({"status": "error", "message": "Invalid API Key."})

    storage_bytes = 0
    file_count = 0
    for fname in os.listdir(UPLOAD_FOLDER):
        if fname.startswith(api_key + "_"):
            storage_bytes += os.path.getsize(os.path.join(UPLOAD_FOLDER, fname))
            file_count += 1

    db_file = os.path.join(DATA_DIR, f"{api_key}_db.json")
    auth_file = os.path.join(DATA_DIR, f"{api_key}_auth.json")
    db_bytes = os.path.getsize(db_file) if os.path.exists(db_file) else 0
    auth_bytes = os.path.getsize(auth_file) if os.path.exists(auth_file) else 0
    total = storage_bytes + db_bytes + auth_bytes

    return jsonify({
        "status": "success",
        "storage": format_bytes(storage_bytes),
        "storage_bytes": storage_bytes,
        "database": format_bytes(db_bytes),
        "authentication": format_bytes(auth_bytes),
        "total": format_bytes(total),
        "total_bytes": total,
        "file_count": file_count
    })

# ==========================================
#         RULES API
# ==========================================
@app.route('/api/rules', methods=['POST'])
def rules_api():
    data = request.json or {}
    api_key = data.get('api_key')
    action = data.get('action', 'get')
    user_id, _ = get_dev_by_api_key(api_key)
    if not user_id:
        return jsonify({"status": "error", "message": "Invalid API Key."})

    rules_file = os.path.join(DATA_DIR, f"{api_key}_rules.json")
    default_rules = '{\n  "rules": {\n    ".read": "true",\n    ".write": "true"\n  }\n}'

    if action == 'get':
        if os.path.exists(rules_file):
            with open(rules_file) as f:
                return jsonify({"status": "success", "rules": f.read()})
        return jsonify({"status": "success", "rules": default_rules})

    elif action == 'update':
        rules_text = data.get('rules', default_rules)
        try:
            json.loads(rules_text)  # validate JSON
        except:
            return jsonify({"status": "error", "message": "Invalid JSON format."})
        with open(rules_file, 'w') as f:
            f.write(rules_text)
        return jsonify({"status": "success", "message": "Rules updated!"})

    return jsonify({"status": "error", "message": "Invalid action."})

# ==========================================
#         START SERVER
# ==========================================
if __name__ == '__main__':
    print("=" * 45)
    print("   ☁️  CloudNest API Server v2.0")
    print("=" * 45)
    print(f"🌐 Server : {get_host_url()}")
    print(f"📌 Port   : {PORT}")
    print(f"📁 Data   : {os.path.abspath(DATA_DIR)}")
    print(f"🔔 Ping   : {get_host_url()}/ping  ← Cron-job.org এ এটা দাও")
    print("=" * 45)
    app.run(host="0.0.0.0", port=PORT, use_reloader=False)

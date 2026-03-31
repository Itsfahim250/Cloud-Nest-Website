import json
import os
import uuid
import hashlib
from datetime import datetime
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

ADMIN_EMAIL = "ufbfahimyt250@gmail.com"

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
    return "cn_" + hashlib.sha256(email.encode()).hexdigest()[:32]

def get_dev_by_api_key(api_key):
    devs = load_devs()
    for email, info in devs.items():
        if info.get('api_key') == api_key:
            return email, info
    return None, None

def get_host_url():
    return os.environ.get("RENDER_EXTERNAL_URL", "https://cloud-nest-website.onrender.com").rstrip('/')

def format_bytes(b):
    if b < 1024: return f"{b} B"
    elif b < 1024**2: return f"{b/1024:.2f} KB"
    elif b < 1024**3: return f"{b/1024**2:.2f} MB"
    else: return f"{b/1024**3:.2f} GB"

def check_monthly_limit(dev_info, limit_type, amount=1):
    if dev_info.get('plan') == 'premium':
        return True, ""
        
    current_month = datetime.now().strftime('%Y-%m')
    usage = dev_info.get('usage', {})
    if current_month not in usage:
        usage[current_month] = {"db": 0, "storage": 0, "auth": 0}
        
    LIMITS = {"db": 25 * 1024**3, "storage": 10 * 1024**3, "auth": 250}
    
    if usage[current_month].get(limit_type, 0) + amount > LIMITS[limit_type]:
        return False, f"Monthly limit exceeded for {limit_type}. Please upgrade to Premium."
    
    return True, usage

def update_monthly_limit(email, limit_type, amount=1):
    devs = load_devs()
    if email in devs:
        current_month = datetime.now().strftime('%Y-%m')
        if 'usage' not in devs[email]: devs[email]['usage'] = {}
        if current_month not in devs[email]['usage']: devs[email]['usage'][current_month] = {"db": 0, "storage": 0, "auth": 0}
        devs[email]['usage'][current_month][limit_type] += amount
        save_devs(devs)

# ==========================================
#         KEEP-ALIVE
# ==========================================
@app.route('/ping')
def ping():
    return "ok", 200

@app.route('/')
def home():
    return jsonify({"status": "ok", "service": "CloudNest API", "version": "3.0"})

# ==========================================
#         DIRECT AUTHENTICATION (NO OTP)
# ==========================================
@app.route('/api/dev/auth', methods=['POST'])
def dev_auth():
    data = request.json or {}
    email = data.get('email', '').strip().lower()
    action = data.get('action', '')
    password = data.get('password', '')
    
    if not email.endswith('@gmail.com'):
        return jsonify({"status": "error", "message": "Only @gmail.com is allowed!"})
        
    devs = load_devs()
    
    if action == 'register':
        if email in devs:
            return jsonify({"status": "error", "message": "This email is already registered."})
        name = data.get('name', '')
        api_key = generate_api_key(email)
        devs[email] = {"name": name, "email": email, "password": password, "api_key": api_key, "plan": "free", "usage": {}}
        save_devs(devs)
        return jsonify({"status": "success", "message": "Registration successful!", "api_key": api_key, "name": name, "email": email, "plan": "free"})
        
    elif action == 'login':
        if email not in devs:
            return jsonify({"status": "error", "message": "Email not found. Please register."})
        if devs[email].get('password') != password:
            return jsonify({"status": "error", "message": "Incorrect password."})
        
        info = devs[email]
        return jsonify({"status": "success", "message": "Login successful!", "api_key": info['api_key'], "name": info['name'], "email": email, "plan": info.get('plan', 'free')})
        
    elif action == 'forgot':
        if email not in devs:
            return jsonify({"status": "error", "message": "Email not found."})
        new_password = data.get('new_password', '')
        devs[email]['password'] = new_password
        save_devs(devs)
        return jsonify({"status": "success", "message": "Password updated successfully!"})

    return jsonify({"status": "error", "message": "Invalid action."})

# ==========================================
#         ADMIN PREMIUM FEATURE
# ==========================================
@app.route('/api/admin/make-premium', methods=['POST'])
def make_premium():
    data = request.json or {}
    api_key = data.get('api_key')
    target_email = data.get('target_email', '').strip().lower()
    
    user_email, _ = get_dev_by_api_key(api_key)
    if user_email != ADMIN_EMAIL:
        return jsonify({"status": "error", "message": "Unauthorized. Admin only."})
        
    devs = load_devs()
    if target_email in devs:
        devs[target_email]['plan'] = 'premium'
        save_devs(devs)
        return jsonify({"status": "success", "message": f"{target_email} has been upgraded to Premium!"})
    return jsonify({"status": "error", "message": "User not found."})

# ==========================================
#         DATABASE, AUTH, STORAGE APIs
# ==========================================
@app.route('/api/db', methods=['POST'])
def api_db():
    data = request.json or {}
    api_key = data.get('api_key')
    action = data.get('action')
    key = data.get('key', 'default')
    payload = data.get('data', '')

    user_email, dev_info = get_dev_by_api_key(api_key)
    if not user_email: return jsonify({"status": "error", "message": "Invalid API Key."})

    db_file = os.path.join(DATA_DIR, f"{api_key}_db.json")
    db_data = {}
    if os.path.exists(db_file):
        with open(db_file, "r") as f: db_data = json.load(f)

    if action in ['save', 'edit']:
        payload_size = len(str(payload).encode('utf-8'))
        allowed, msg = check_monthly_limit(dev_info, 'db', payload_size)
        if not allowed: return jsonify({"status": "error", "message": msg})
        
        db_data[key] = payload
        with open(db_file, "w") as f: json.dump(db_data, f, indent=2)
        update_monthly_limit(user_email, 'db', payload_size)
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

    return jsonify({"status": "error", "message": "Invalid action."})

@app.route('/api/auth', methods=['POST'])
def api_auth():
    data = request.json or {}
    api_key = data.get('api_key')
    action = data.get('action')
    username = data.get('username', '')
    password = data.get('password', '')

    user_email, dev_info = get_dev_by_api_key(api_key)
    if not user_email: return jsonify({"status": "error", "message": "Invalid API Key."})

    auth_file = os.path.join(DATA_DIR, f"{api_key}_auth.json")
    auth_data = {}
    if os.path.exists(auth_file):
        with open(auth_file, "r") as f: auth_data = json.load(f)

    if action == 'register':
        if username in auth_data: return jsonify({"status": "error", "message": "User already exists!"})
        allowed, msg = check_monthly_limit(dev_info, 'auth', 1)
        if not allowed: return jsonify({"status": "error", "message": msg})
        
        uid = str(uuid.uuid4())
        auth_data[username] = {"password": password, "uid": uid}
        with open(auth_file, "w") as f: json.dump(auth_data, f, indent=2)
        update_monthly_limit(user_email, 'auth', 1)
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

@app.route('/api/upload', methods=['POST'])
def upload_file():
    api_key = request.form.get('api_key')
    user_email, dev_info = get_dev_by_api_key(api_key)
    if not user_email: return jsonify({"status": "error", "message": "Invalid API key"})

    if 'file' not in request.files: return jsonify({"status": "error", "message": "No file uploaded"})
    file = request.files['file']
    if file.filename == '': return jsonify({"status": "error", "message": "Empty file"})
    
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)
    
    allowed, msg = check_monthly_limit(dev_info, 'storage', file_size)
    if not allowed: return jsonify({"status": "error", "message": msg})

    filename = secure_filename(file.filename)
    unique_filename = f"{api_key}_{uuid.uuid4().hex[:8]}_{filename}"
    filepath = os.path.join(UPLOAD_FOLDER, unique_filename)
    file.save(filepath)
    update_monthly_limit(user_email, 'storage', file_size)
    
    file_url = f"{get_host_url()}/uploads/{unique_filename}"
    return jsonify({"status": "success", "url": file_url, "filename": unique_filename, "size": format_bytes(file_size)})

@app.route('/api/storage/list', methods=['POST'])
def list_files():
    data = request.json or {}
    api_key = data.get('api_key')
    user_email, _ = get_dev_by_api_key(api_key)
    if not user_email: return jsonify({"status": "error", "message": "Invalid API Key."})

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
    user_email, _ = get_dev_by_api_key(api_key)
    if not user_email: return jsonify({"status": "error", "message": "Invalid API Key."})
    if not filename.startswith(api_key + "_"): return jsonify({"status": "error", "message": "Unauthorized."})
    
    fpath = os.path.join(UPLOAD_FOLDER, filename)
    if os.path.exists(fpath): os.remove(fpath)
    return jsonify({"status": "success", "message": "File deleted."})

@app.route('/uploads/<filename>')
def serve_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route('/api/usage', methods=['POST'])
def usage():
    data = request.json or {}
    api_key = data.get('api_key')
    user_email, dev_info = get_dev_by_api_key(api_key)
    if not user_email: return jsonify({"status": "error", "message": "Invalid API Key."})

    current_month = datetime.now().strftime('%Y-%m')
    usage_data = dev_info.get('usage', {}).get(current_month, {"db": 0, "storage": 0, "auth": 0})
    
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
        "plan": dev_info.get('plan', 'free'),
        "month": current_month,
        "monthly_usage": usage_data,
        "storage": format_bytes(storage_bytes),
        "database": format_bytes(db_bytes),
        "authentication": format_bytes(auth_bytes),
        "total": format_bytes(total),
        "file_count": file_count
    })

@app.route('/api/rules', methods=['POST'])
def rules_api():
    data = request.json or {}
    api_key = data.get('api_key')
    action = data.get('action', 'get')
    user_email, _ = get_dev_by_api_key(api_key)
    if not user_email: return jsonify({"status": "error", "message": "Invalid API Key."})

    rules_file = os.path.join(DATA_DIR, f"{api_key}_rules.json")
    default_rules = '{\n  "rules": {\n    ".read": "true",\n    ".write": "true"\n  }\n}'

    if action == 'get':
        if os.path.exists(rules_file):
            with open(rules_file) as f: return jsonify({"status": "success", "rules": f.read()})
        return jsonify({"status": "success", "rules": default_rules})

    elif action == 'update':
        rules_text = data.get('rules', default_rules)
        try: json.loads(rules_text)
        except: return jsonify({"status": "error", "message": "Invalid JSON format."})
        with open(rules_file, 'w') as f: f.write(rules_text)
        return jsonify({"status": "success", "message": "Rules updated!"})

    return jsonify({"status": "error", "message": "Invalid action."})

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=PORT, use_reloader=False)

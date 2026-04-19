from flask import Flask, render_template, request, redirect, session
import os
from datetime import datetime, timedelta
import json
import psycopg2
from werkzeug.security import generate_password_hash, check_password_hash
from flask import send_from_directory
import gspread
from oauth2client.service_account import ServiceAccountCredentials

import cloudinary
import cloudinary.uploader

# ---------------- CLOUDINARY ----------------
cloudinary.config(
    cloud_name=os.getenv("CLOUD_NAME"),
    api_key=os.getenv("CLOUD_API_KEY"),
    api_secret=os.getenv("CLOUD_API_SECRET")
)

# ---------------- APP ----------------
app = Flask(__name__, static_folder='static', static_url_path='/static')

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE="Lax"
)

app.secret_key = os.getenv("SECRET_KEY")
app.permanent_session_lifetime = timedelta(hours=8)

REGISTER_KEY = "noc123"

# 🔥 RATE LIMIT COM EXPIRAÇÃO
login_tentativas = {}

# ---------------- DATABASE ----------------
def get_db():
    return psycopg2.connect(os.getenv("DATABASE_URL"))

# ---------------- GOOGLE SHEETS ----------------
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds_dict = json.loads(os.getenv("GOOGLE_CREDS"))
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)
sheet = client.open("ata-online").sheet1

def enviar_para_sheets(id_registro, destinatario, descricao, responsavel, imagem):
    try:
        sheet.append_row([
            id_registro,
            destinatario,
            descricao,
            responsavel,
            imagem,
            "pendente",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ])
    except Exception as e:
        print("ERRO SHEETS:", e)

def atualizar_status_sheets(id_registro):
    try:
        records = sheet.get_all_values()
        for i, row in enumerate(records):
            if str(row[0]) == str(id_registro):
                sheet.update_cell(i + 1, 6, "entregue")
                break
    except Exception as e:
        print("ERRO UPDATE SHEETS:", e)

# ---------------- HELPERS ----------------
def is_admin():
    return session.get("role") == "admin"

def log_action(user_id, acao, detalhes=""):
    try:
        db = get_db()
        cur = db.cursor()
        cur.execute("""
            INSERT INTO logs (user_id, acao, detalhes)
            VALUES (%s, %s, %s)
        """, (user_id, acao, detalhes))
        db.commit()
        cur.close()
        db.close()
    except:
        pass

# ---------------- AUTH ----------------

@app.route("/register", methods=["GET", "POST"])
def register():
    error = None

    if request.method == "POST":
        db = get_db()
        cur = db.cursor()

        username = request.form["username"].strip()
        password = request.form["password"]
        register_key = request.form["register_key"]

        if register_key != REGISTER_KEY:
            error = "Código inválido"

        elif len(password) < 4:
            error = "Senha muito curta"

        else:
            cur.execute("SELECT id FROM usuarios WHERE username=%s", (username,))
            if cur.fetchone():
                error = "Usuário já existe"
            else:
                cur.execute("SELECT id FROM unidades LIMIT 1")
                unidade = cur.fetchone()

                cur.execute("""
                    INSERT INTO usuarios (username, password, unidade_id, role)
                    VALUES (%s, %s, %s, 'user')
                """, (
                    username,
                    generate_password_hash(password),
                    unidade[0]
                ))

                db.commit()
                return redirect("/login")

        cur.close()
        db.close()

    return render_template("register.html", error=error)


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        ip = request.remote_addr

        tent = login_tentativas.get(ip)

        if tent:
            if tent["count"] >= 5 and (datetime.now() - tent["time"]).seconds < 600:
                return "Muitas tentativas, tente novamente depois"

        db = get_db()
        cur = db.cursor()

        cur.execute("""
            SELECT id, username, password, unidade_id, role
            FROM usuarios WHERE username=%s
        """, (request.form["username"],))

        user = cur.fetchone()

        cur.close()
        db.close()

        if not user or not check_password_hash(user[2], request.form["password"]):
            login_tentativas[ip] = {
                "count": tent["count"] + 1 if tent else 1,
                "time": datetime.now()
            }
            error = "Credenciais inválidas"

        else:
            session["user_id"] = user[0]
            session["username"] = user[1]
            session["unidade_id"] = user[3]
            session["role"] = user[4]

            login_tentativas[ip] = {"count": 0, "time": datetime.now()}

            log_action(user[0], "LOGIN")

            return redirect("/")

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# ---------------- INDEX ----------------
@app.route("/")
def index():
    if "user_id" not in session:
        return redirect("/login")

    db = get_db()
    cur = db.cursor()

    q = request.args.get("q", "").strip()

    # 🔴 ADMIN → vê tudo
    if session["role"] == "admin":
        if q:
            cur.execute("""
                SELECT * FROM atas_saida
                WHERE destinatario ILIKE %s OR descricao ILIKE %s
                ORDER BY id DESC LIMIT 100
            """, (f"%{q}%", f"%{q}%"))
        else:
            cur.execute("""
                SELECT * FROM atas_saida
                ORDER BY id DESC LIMIT 100
            """)

    # 🟡 ADMIN UNIDADE → vê tudo da unidade
    elif session["role"] == "unit_admin":
        if q:
            cur.execute("""
                SELECT * FROM atas_saida
                WHERE unidade_id=%s
                AND (destinatario ILIKE %s OR descricao ILIKE %s)
                ORDER BY id DESC LIMIT 100
            """, (session["unidade_id"], f"%{q}%", f"%{q}%"))
        else:
            cur.execute("""
                SELECT * FROM atas_saida
                WHERE unidade_id=%s
                ORDER BY id DESC LIMIT 100
            """, (session["unidade_id"],))

    # 🔵 USER → só suas atas
    else:
        if q:
            cur.execute("""
                SELECT * FROM atas_saida
                WHERE usuario_id=%s
                AND (destinatario ILIKE %s OR descricao ILIKE %s)
                ORDER BY id DESC LIMIT 100
            """, (session["user_id"], f"%{q}%", f"%{q}%"))
        else:
            cur.execute("""
                SELECT * FROM atas_saida
                WHERE usuario_id=%s
                ORDER BY id DESC LIMIT 100
            """, (session["user_id"],))

    atas = cur.fetchall()

    # 📊 métricas
    total = len(atas)
    pendentes = len([a for a in atas if a[4] == "pendente"])
    entregues = len([a for a in atas if a[4] == "entregue"])

    cur.close()
    db.close()

    # 🔥 RETORNO (ESSENCIAL)
    return render_template(
        "index.html",
        atas=atas,
        total=total,
        pendentes=pendentes,
        entregues=entregues,
        username=session.get("username")
    )

# ---------------- ADD ----------------

@app.route("/add", methods=["POST"])
def add():
    if "user_id" not in session:
        return redirect("/login")

    destinatario = request.form["destinatario"].strip()
    descricao = request.form["descricao"].strip()
    responsavel = request.form["responsavel"].strip()

    if not destinatario or not descricao or not responsavel:
        return "Campos inválidos"

    db = get_db()
    cur = db.cursor()

    file = request.files.get("imagem")
    image_url = ""

    if file and file.filename:
        if not file.filename.lower().endswith((".png",".jpg",".jpeg",".webp")):
            return "Formato inválido"

        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)

        if size > 5 * 1024 * 1024:
            return "Imagem muito grande"

        result = cloudinary.uploader.upload(file)
        image_url = result["secure_url"]

    cur.execute("""
        INSERT INTO atas_saida
        (destinatario, descricao, responsavel, imagem, usuario_id, unidade_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (
        destinatario,
        descricao,
        responsavel,
        image_url,
        session["user_id"],
        session["unidade_id"]
    ))

    id_registro = cur.fetchone()[0]
    db.commit()

    enviar_para_sheets(id_registro, destinatario, descricao, responsavel, image_url)
    log_action(session["user_id"], "CREATE_ATA", destinatario)

    cur.close()
    db.close()

    return redirect("/")

# ---------------- DONE ----------------

@app.route("/done/<int:id>", methods=["POST"])
def done(id):
    if "user_id" not in session:
        return redirect("/login")

    db = get_db()
    cur = db.cursor()

    # 🔴 ADMIN SISTEMA → pode tudo
    if session["role"] == "admin":
        cur.execute(
            "UPDATE atas_saida SET status='entregue' WHERE id=%s",
            (id,)
        )

    # 🟡 ADMIN UNIDADE → só da unidade
    elif session["role"] == "unit_admin":
        cur.execute("""
            UPDATE atas_saida
            SET status='entregue'
            WHERE id=%s AND unidade_id=%s
        """, (id, session["unidade_id"]))

    # 🔵 USER → só as próprias atas
    else:
        cur.execute("""
            UPDATE atas_saida
            SET status='entregue'
            WHERE id=%s AND usuario_id=%s
        """, (id, session["user_id"]))

    db.commit()

    atualizar_status_sheets(id)
    log_action(session["user_id"], "DONE_ATA", f"id={id}")

    cur.close()
    db.close()

    return redirect("/")

# ---------------- ADMIN UNIDADES ----------------

@app.route("/admin/unidades", methods=["GET", "POST"])
def admin_unidades():
    if not is_admin():
        return "Acesso negado", 403

    db = get_db()
    cur = db.cursor()

    if request.method == "POST":
        nome = request.form["nome"].strip()

        if not nome:
            return "Nome inválido"

        try:
            cur.execute("INSERT INTO unidades (nome) VALUES (%s)", (nome,))
            db.commit()
        except:
            return "Unidade já existe"

    cur.execute("SELECT id, nome FROM unidades ORDER BY nome")
    unidades = cur.fetchall()

    cur.close()
    db.close()

    return render_template("unidades.html", unidades=unidades)

# ---------------- ADMIN USERS ----------------

@app.route("/admin/users", methods=["GET", "POST"])
def admin_users():
    if not is_admin():
        return "Acesso negado", 403

    db = get_db()
    cur = db.cursor()

    if request.method == "POST":
        cur.execute("""
            UPDATE usuarios
            SET unidade_id=%s, role=%s
            WHERE id=%s
        """, (
            request.form["unidade_id"],
            request.form["role"],
            request.form["user_id"]
        ))
        db.commit()

    cur.execute("""
        SELECT u.id, u.username, u.role, un.nome, un.id
        FROM usuarios u
        LEFT JOIN unidades un ON u.unidade_id = un.id
        ORDER BY u.id
    """)
    users = cur.fetchall()

    cur.execute("SELECT id, nome FROM unidades")
    unidades = cur.fetchall()

    cur.close()
    db.close()

    return render_template("admin_users.html", users=users, unidades=unidades)

# ---------------- DELETE USER ----------------

@app.route("/admin/delete_user/<int:id>", methods=["POST"])
def delete_user(id):
    if not is_admin():
        return "Acesso negado", 403

    db = get_db()
    cur = db.cursor()

    cur.execute("DELETE FROM usuarios WHERE id=%s", (id,))
    db.commit()

    log_action(session["user_id"], "DELETE_USER", f"user={id}")

    cur.close()
    db.close()

    return redirect("/admin/users")

#-----------------uplodad -----------
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory('uploads', filename)
# ---------------- LOGS ----------------

@app.route("/admin/logs")
def logs():
    if not is_admin():
        return "Acesso negado", 403

    db = get_db()
    cur = db.cursor()

    cur.execute("""
        SELECT l.id, u.username, l.acao, l.detalhes, l.criado_em
        FROM logs l
        LEFT JOIN usuarios u ON u.id = l.user_id
        ORDER BY l.id DESC LIMIT 100
    """)

    logs = cur.fetchall()

    cur.close()
    db.close()

    return render_template("logs.html", logs=logs)

# ---------------- SECURITY ----------------

@app.after_request
def headers(resp):
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-XSS-Protection"] = "1; mode=block"
    return resp

# ---------------- RUN ----------------

if __name__ == "__main__":
    app.run()
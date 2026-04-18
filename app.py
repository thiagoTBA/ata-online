from flask import Flask, render_template, request, redirect, session
import os
from datetime import datetime, timedelta
import json
from flask import send_from_directory
import psycopg2
from werkzeug.security import generate_password_hash, check_password_hash

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

app.secret_key = os.getenv("SECRET_KEY")  # ❗ SEM fallback fraco
app.permanent_session_lifetime = timedelta(hours=8)

REGISTER_KEY = "noc123"

# ---------------- LOGIN PROTECTION ----------------

login_tentativas = {}


# ---------------- DATABASE ----------------

def get_db():
    try:
        return psycopg2.connect(os.getenv("DATABASE_URL"))
    except Exception as e:
        print("ERRO DB:", e)
        raise

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

# ---------------- AUTH ----------------

@app.route("/version")
def version():
    return "VERSAO NOVA OK"

@app.route("/register", methods=["GET", "POST"])
def register():
    error = None

    if request.method == "POST":
        db = get_db()
        cursor = db.cursor()

        username = request.form["username"].strip()
        password = request.form["password"]
        register_key = request.form["register_key"]

        if register_key != REGISTER_KEY:
            error = "Código inválido"

        elif len(password) < 4:
            error = "Senha muito curta"

        elif not username:
            error = "Usuário inválido"

        else:
            try:
                cursor.execute(
                    "INSERT INTO usuarios (username, password) VALUES (%s, %s)",
                    (username, generate_password_hash(password))
                )
                db.commit()
                return redirect("/login")
            except Exception as e:
                print("ERRO REGISTER:", e)
                error = "Erro ao criar usuário"

        cursor.close()
        db.close()

    return render_template("register.html", error=error)

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        ip = request.remote_addr

        if ip in login_tentativas and login_tentativas[ip] >= 5:
            return "Muitas tentativas. Tente novamente mais tarde."

        db = get_db()
        cursor = db.cursor()

        username = request.form["username"]
        password = request.form["password"]
        remember = request.form.get("remember")

        cursor.execute(
            "SELECT * FROM usuarios WHERE username=%s",
            (username,)
        )

        user = cursor.fetchone()

        cursor.close()
        db.close()

        if not user:
            error = "Usuário não existe"
            login_tentativas[ip] = login_tentativas.get(ip, 0) + 1

        elif not check_password_hash(user[2], password):
            error = "Senha incorreta"
            login_tentativas[ip] = login_tentativas.get(ip, 0) + 1

        else:
            session["user_id"] = user[0]
            session["username"] = user[1]

            login_tentativas[ip] = 0

            if remember:
                session.permanent = True

            return redirect("/")

    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# ---------------- ROTAS ----------------

@app.route("/")
def index():
    if "user_id" not in session:
        return redirect("/login")

    db = get_db()
    cursor = db.cursor()

    q = request.args.get("q", "").strip()
    user_id = session["user_id"]

    if q:
        cursor.execute("""
            SELECT * FROM atas_saida
            WHERE usuario_id=%s AND (destinatario ILIKE %s OR descricao ILIKE %s)
            ORDER BY id DESC
        """, (user_id, f"%{q}%", f"%{q}%"))
    else:
        cursor.execute("""
            SELECT * FROM atas_saida
            WHERE usuario_id=%s
            ORDER BY id DESC
        """, (user_id,))

    atas = cursor.fetchall()

    # 🔥 DASHBOARD
    cursor.execute(
        "SELECT COUNT(*) FROM atas_saida WHERE usuario_id=%s",
        (user_id,)
    )
    total = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM atas_saida WHERE status='pendente' AND usuario_id=%s",
        (user_id,)
    )
    pendentes = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM atas_saida WHERE status='entregue' AND usuario_id=%s",
        (user_id,)
    )
    entregues = cursor.fetchone()[0]

    cursor.close()
    db.close()

    return render_template(
        "index.html",
        atas=atas,
        pendentes=pendentes,
        entregues=entregues,
        total=total,
        username=session.get("username")
    )

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
    cursor = db.cursor()

    file = request.files.get("imagem")
    image_url = ""

    # 🔐 VALIDA UPLOAD
    if file and file.filename:
        if not file.content_type.startswith("image/"):
            return "Arquivo inválido"

        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)

        if size > 5 * 1024 * 1024:
            return "Imagem muito grande (máx 5MB)"

        try:
            result = cloudinary.uploader.upload(
                file,
                quality="auto",
                fetch_format="auto"
            )
            image_url = result["secure_url"]
        except Exception as e:
            print("ERRO UPLOAD:", e)

    cursor.execute("""
        INSERT INTO atas_saida (destinatario, descricao, responsavel, imagem, usuario_id)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
    """, (destinatario, descricao, responsavel, image_url, session["user_id"]))

    id_registro = cursor.fetchone()[0]
    db.commit()

    enviar_para_sheets(
        id_registro,
        destinatario,
        descricao,
        responsavel,
        image_url
    )

    cursor.close()
    db.close()

    return redirect("/")

@app.route("/done/<int:id>")
def done(id):
    if "user_id" not in session:
        return redirect("/login")

    db = get_db()
    cursor = db.cursor()

    cursor.execute(
        "UPDATE atas_saida SET status='entregue' WHERE id=%s AND usuario_id=%s",
        (id, session["user_id"])
    )

    db.commit()

    atualizar_status_sheets(id)

    cursor.close()
    db.close()

    return redirect("/")

# ---------------- SHEETS UPDATE ----------------

def atualizar_status_sheets(id_registro):
    try:
        records = sheet.get_all_values()

        for i, row in enumerate(records):
            if str(row[0]) == str(id_registro):
                sheet.update_cell(i + 1, 6, "entregue")  # ✔ coluna correta
                break

    except Exception as e:
        print("ERRO UPDATE SHEETS:", e)

# ---------------- HEADERS SEGURANÇA ----------------

@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response

# ---------------- APP ----------------



# ---------------- RUN ----------------

if __name__ == "__main__":
    app.run()
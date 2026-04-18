from flask import Flask, render_template, request, redirect, send_from_directory, session
import os
import uuid
from datetime import datetime
import json

import psycopg2
from werkzeug.security import generate_password_hash, check_password_hash

import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "devkey")

REGISTER_KEY = "noc123"

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

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

def enviar_para_sheets(id_registro, destinatario, descricao, responsavel):
    try:
        sheet.append_row([
            id_registro,
            destinatario,
            descricao,
            responsavel,
            "pendente",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ])
    except Exception as e:
        print("ERRO SHEETS:", e)

# ---------------- AUTH ----------------

@app.route("/register", methods=["GET", "POST"])
def register():
    error = None

    if request.method == "POST":
        db = get_db()
        cursor = db.cursor()

        username = request.form["username"]
        password = request.form["password"]
        register_key = request.form["register_key"]

        if register_key != REGISTER_KEY:
            error = "Código inválido"

        elif len(password) < 4:
            error = "Senha muito curta"

        else:
            try:
                cursor.execute(
                    "INSERT INTO usuarios (username, password) VALUES (%s, %s)",
                    (username, generate_password_hash(password))
                )
                db.commit()
                return redirect("/login")
            except Exception:
                error = "Erro ao criar usuário"

        cursor.close()
        db.close()

    return render_template("register.html", error=error)

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
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

        elif not check_password_hash(user[2], password):
            error = "Senha incorreta"

        else:
            session["user_id"] = user[0]
            session["username"] = user[1]

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

    q = request.args.get("q")
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

    cursor.execute(
        "SELECT COUNT(*) FROM atas_saida WHERE status='pendente' AND usuario_id=%s",
        (user_id,)
    )
    pendentes = cursor.fetchone()[0]

    cursor.close()
    db.close()

    username = session.get("username")

    return render_template("index.html", atas=atas, pendentes=pendentes, username=username)

@app.route("/add", methods=["POST"])
def add():
    if "user_id" not in session:
        return redirect("/login")

    db = get_db()
    cursor = db.cursor()

    destinatario = request.form["destinatario"]
    descricao = request.form["descricao"]
    responsavel = request.form["responsavel"]
    user_id = session["user_id"]

    file = request.files.get("imagem")
    filename = ""

    if file and file.filename:
        ext = file.filename.split(".")[-1]
        filename = f"{uuid.uuid4()}.{ext}"
        file.save(os.path.join(UPLOAD_FOLDER, filename))

    cursor.execute("""
        INSERT INTO atas_saida (destinatario, descricao, responsavel, imagem, usuario_id)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
    """, (destinatario, descricao, responsavel, filename, user_id))

    id_registro = cursor.fetchone()[0]

    db.commit()

    # 🔥 ENVIA PRO SHEETS
    enviar_para_sheets(id_registro, destinatario, descricao, responsavel)

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
        "UPDATE atas_saida SET status='entregue' WHERE id=%s",
        (id,)
    )

    db.commit()
    cursor.close()
    db.close()

    return redirect("/")

@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

# ---------------- RUN ----------------

if __name__ == "__main__":
    app.run()
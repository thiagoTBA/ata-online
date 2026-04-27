from flask import Blueprint, render_template, request, redirect, session
from werkzeug.security import check_password_hash
from datetime import datetime

from services.db import get_db
from services.utils import log_action

auth_bp = Blueprint("auth", __name__)


# 🔥 RATE LIMIT (mesmo comportamento do app.py)
login_tentativas = {}


# ---------------- LOGIN ----------------
@auth_bp.route("/login", methods=["GET", "POST"])
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
            
            if session["role"] == "secretaria":
                return redirect("/secretaria")

            elif session["role"] == "coordenacao":
                return redirect("/coordenacao")

            elif session["role"] in ["admin", "unit_admin"]:
                return redirect("/admin/users")

            else:
                return redirect("/")

    return render_template("login.html", error=error)


# ---------------- LOGOUT ----------------
@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect("/login")




@auth_bp.route("/change_password", methods=["POST"])
def change_password():
    if "user_id" not in session:
        return redirect("/login")

    atual = request.form.get("atual")
    nova = request.form.get("nova")

    if not atual or not nova:
        return "Preencha todos os campos", 400

    if len(nova) < 6:
        return "Senha muito curta", 400

    db = get_db()
    cur = db.cursor()

    # 🔍 pega hash atual
    cur.execute("SELECT password FROM usuarios WHERE id=%s", (session["user_id"],))
    row = cur.fetchone()

    if not row:
        return "Usuário inválido", 400

    hash_db = row[0]

    # 🔒 valida senha atual
    from werkzeug.security import check_password_hash, generate_password_hash

    if not check_password_hash(hash_db, atual):
        return "Senha atual incorreta", 400

    # ✅ atualiza
    cur.execute("""
        UPDATE usuarios
        SET password=%s
        WHERE id=%s
    """, (
        generate_password_hash(nova),
        session["user_id"]
    ))

    db.commit()
    cur.close()
    db.close()

    log_action(session["user_id"], "CHANGE_PASSWORD")

    return redirect("/")


# ---------------- RESET PASS ----------------

from uuid import uuid4
from datetime import datetime, timedelta

# 🔒 RATE LIMIT RESET
reset_tentativas = {}

@auth_bp.route("/esqueci", methods=["GET", "POST"])
def esqueci_senha():
    if request.method == "POST":
        ip = request.remote_addr

        tent = reset_tentativas.get(ip)

        # 🚨 bloqueio por excesso
        if tent:
            if tent["count"] >= 3 and (datetime.now() - tent["time"]).seconds < 300:
                return "Muitas tentativas, tente novamente em alguns minutos"

        username = request.form.get("username")

        if not username:
            return "Informe o usuário", 400

        db = get_db()
        cur = db.cursor()

        cur.execute("SELECT id FROM usuarios WHERE username=%s", (username,))
        user = cur.fetchone()

        if not user:
            return "Usuário não encontrado", 404

        from uuid import uuid4
        from datetime import timedelta

        token = str(uuid4())
        expira = datetime.now() + timedelta(hours=1)

        cur.execute("""
            UPDATE usuarios
            SET reset_token=%s, reset_expira=%s
            WHERE id=%s
        """, (token, expira, user[0]))

        db.commit()
        cur.close()
        db.close()

        # 🔢 atualiza tentativas
        reset_tentativas[ip] = {
            "count": tent["count"] + 1 if tent else 1,
            "time": datetime.now()
        }

        # 🔥 resposta (sem email por enquanto)
        return render_template("reset_link.html", token=token)

    return """
    <h3>Esqueci minha senha</h3>
    <form method="POST">
        <input name="username" placeholder="Usuário" required>
        <button>Recuperar senha</button>
    </form>
    """
@auth_bp.route("/reset/<token>", methods=["GET", "POST"])
def reset_senha(token):
    db = get_db()
    cur = db.cursor()

    cur.execute("""
        SELECT id, reset_expira FROM usuarios
        WHERE reset_token=%s
    """, (token,))

    user = cur.fetchone()

    if not user:
        return "Token inválido", 400

    if datetime.now() > user[1]:
        return "Token expirado", 400

    if request.method == "POST":
        nova = request.form.get("nova")

        if not nova or len(nova) < 6:
            return "Senha muito curta (mínimo 6 caracteres)", 400

        from werkzeug.security import generate_password_hash

        cur.execute("""
            UPDATE usuarios
            SET password=%s,
                reset_token=NULL,
                reset_expira=NULL
            WHERE id=%s
        """, (
            generate_password_hash(nova),
            user[0]
        ))

        db.commit()
        cur.close()
        db.close()

        return redirect("/login")

    return render_template("esqueci.html")
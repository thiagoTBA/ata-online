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

    if len(nova) < 4:
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
from flask import Flask, render_template, request, redirect, session
import os
from datetime import datetime, timedelta
import json
import psycopg2
from werkzeug.security import generate_password_hash, check_password_hash
from flask import send_from_directory
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import psycopg2.extras
import cloudinary
import cloudinary.uploader
import random
import string

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


# ---------------- HELPERS ----------------

def formatar_protocolo(numero):
    ano = datetime.now().year
    return f"CETAM-{ano}-{str(numero).zfill(6)}"

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
# ---------------- HELPERS ----------------

TIPOS = {
    1: "Alterações Cadastrais",
    2: "Mudança de Turno",
    3: "Cancelamento de Matrícula",
    4: "Declaração com Histórico",
    5: "Declaração de Conclusão",
    6: "Declaração de Matrícula",
    7: "Declaração de Frequência",
    8: "Declaração de Comparecimento",
    9: "Declaração de Estágio",
    10: "Declaração de Instrutoria",
    11: "Revisão de Notas",
    12: "2ª Via / Correção",
    13: "2ª Chamada",
    14: "Transferência",
    15: "Certificação Intermediária",
    16: "Histórico Escolar",
    17: "Diploma/Certificado",
    18: "Reoferta",
    19: "Aproveitamento",
    20: "Atividade Domiciliar",
    21: "Justificativa de Faltas",
    22: "Outros"
}
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


# ---------------- gera pass ----------------
def gerar_senha(tamanho=6):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=tamanho))
# ---------------- caduser ----------------
@app.route("/admin/create_user", methods=["POST"])
def create_user():
    if session.get("role") not in ["admin", "unit_admin", "secretaria"]:
        return "Sem permissão", 403

    username = request.form.get("username")
    cpf = request.form.get("cpf")
    unidade_id = session.get("unidade_id")

    if not username or not cpf:
        return "Dados obrigatórios", 400

    senha = gerar_senha()
    senha_hash = generate_password_hash(senha)

    db = get_db()
    cur = db.cursor()

    try:
        cur.execute("""
            INSERT INTO usuarios (username, password, unidade_id, role)
            VALUES (%s, %s, %s, %s)
        """, (cpf, senha_hash, unidade_id, "user"))

        db.commit()

    except Exception as e:
        db.rollback()
        return f"Erro: {e}"

    finally:
        cur.close()
        db.close()

    # 🔥 mostra a senha gerada
    return f"""
    <h2>Usuário criado</h2>
    <p><b>Login:</b> {cpf}</p>
    <p><b>Senha:</b> {senha}</p>
    <a href="/">Voltar</a>
    """
# ---------------- INDEX ----------------
@app.route("/")
def index():
    if "user_id" not in session:
        return redirect("/login")

    role = session.get("role")
    unidade_id = session.get("unidade_id")
    user_id = session.get("user_id")

    db = get_db()

    # 🔥 AQUI A CORREÇÃO
    cur = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        if role == "admin":
            cur.execute("""
                SELECT * FROM atas_saida
                ORDER BY id DESC LIMIT 100
            """)

        elif role == "unit_admin":
            cur.execute("""
                SELECT * FROM atas_saida
                WHERE unidade_id=%s
                ORDER BY id DESC LIMIT 100
            """, (unidade_id,))

        else:
            cur.execute("""
                SELECT * FROM atas_saida
                WHERE usuario_id=%s
                ORDER BY id DESC LIMIT 100
            """, (user_id,))

        atas = cur.fetchall()

    finally:
        cur.close()
        db.close()

    # 🔥 PROTOCOLO LIMPO
    for a in atas:
        a["protocolo"] = formatar_protocolo(a["id"])

    return render_template(
        "index.html",
        atas=atas,
        tipos=TIPOS,
        username=session.get("username"),
        role=role
    )


# ---------------- SECRETARIA ----------------
@app.route("/secretaria")
def secretaria():
    if session.get("role") not in ["secretaria", "unit_admin", "admin"]:
        return redirect("/")

    db = get_db()
    cur = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT * FROM atas_saida
        WHERE unidade_id=%s
        ORDER BY id DESC
    """, (session["unidade_id"],))

    atas = cur.fetchall()

    for a in atas:
        a["protocolo"] = formatar_protocolo(a["id"])

    return render_template("secretaria.html", atas=atas, tipos=TIPOS, role=session["role"])


# ---------------- COORDENAÇÃO ----------------
@app.route("/coordenacao")
def coordenacao():
    if session.get("role") not in ["coordenacao", "admin"]:
        return redirect("/")

    db = get_db()
    cur = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT * FROM atas_saida
        WHERE unidade_id=%s
        AND status='AGUARDANDO_COORD'
        ORDER BY id DESC
    """, (session["unidade_id"],))

    atas = cur.fetchall()

    for a in atas:
        a["protocolo"] = formatar_protocolo(a["id"])

    return render_template("coordenacao.html", atas=atas, tipos=TIPOS, role=session["role"])
# ---------------- ADD ----------------

@app.route("/add", methods=["POST"])
def add():
    if "user_id" not in session:
        return redirect("/login")

    aluno_nome = request.form["aluno_nome"]
    cpf = request.form.get("cpf")
    email = request.form.get("email")
    telefone = request.form.get("telefone")
    curso = request.form.get("curso")
    rg = request.form.get("rg")
    sexo = request.form.get("sexo")
    turno = request.form.get("turno")
    municipio = request.form.get("municipio")
    projeto = request.form.get("projeto")

    tipo = int(request.form["tipo"])
    justificativa = request.form.get("justificativa")

    # 📎 upload
    file = request.files.get("anexo")
    anexo_url = None

    allowed = (".pdf", ".png", ".jpg", ".jpeg")

    if file and file.filename:
        filename = file.filename.lower()

        if not filename.endswith(allowed):
            return "Arquivo inválido"

        # 🔒 limite de tamanho (opcional mas recomendado)
        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)

        if size > 5 * 1024 * 1024:
            return "Arquivo muito grande (máx 5MB)"

        result = cloudinary.uploader.upload(file)
        anexo_url = result["secure_url"]

    # 🔥 regra de fluxo
    if tipo in [2,11,13,18,19,20,21,22]:
        status = "AGUARDANDO_COORD"
    else:
        status = "EM_ATENDIMENTO"

    db = get_db()
    cur = db.cursor()

    cur.execute("""
        INSERT INTO atas_saida
        (aluno_nome, cpf, email, telefone, curso,
         tipo, justificativa, status,
         anexo_url,
         rg, sexo, turno, municipio, projeto,
         usuario_id, unidade_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        aluno_nome, cpf, email, telefone, curso,
        tipo, justificativa, status,
        anexo_url,
        rg, sexo, turno, municipio, projeto,
        session["user_id"], session["unidade_id"]
    ))

    db.commit()
    cur.close()
    db.close()

    return redirect("/")

# ---------------- SECRETARIA ----------
@app.route("/atender/<int:id>", methods=["POST"])
def atender(id):
    if "user_id" not in session:
        return redirect("/login")

    # 🔒 PERMISSÃO
    if session.get("role") not in ["admin", "secretaria"]:
        return "Sem permissão", 403

    db = get_db()
    cur = db.cursor()

    cur.execute("""
        UPDATE atas_saida
        SET
          atendente=%s,
          data_atendimento=NOW(),
          status='EM_ATENDIMENTO'
        WHERE id=%s
    """, (
        session["username"],
        id
    ))

    db.commit()
    cur.close()
    db.close()

    return redirect("/")
# ---------------- COORDENAÇÃO ----------------
@app.route("/parecer/<int:id>", methods=["POST"])
def parecer(id):
    if "user_id" not in session:
        return redirect("/login")

    # 🔒 PERMISSÃO
    if session.get("role") not in ["admin", "coordenacao"]:
        return "Sem permissão", 403

    parecer = request.form["parecer"]
    status = request.form["status"]

    db = get_db()
    cur = db.cursor()

    cur.execute("""
        UPDATE atas_saida
        SET
          parecer=%s,
          coordenador=%s,
          data_parecer=NOW(),
          status=%s
        WHERE id=%s
    """, (
        parecer,
        session["username"],
        status,
        id
    ))

    db.commit()
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
    if "user_id" not in session:
        return redirect("/login")

    role = session.get("role")
    unidade_id = session.get("unidade_id")

    if role not in ["admin", "unit_admin"]:
        return "Acesso negado", 403

    db = get_db()
    cur = db.cursor()

    # ---------------- UPDATE ----------------
    if request.method == "POST":
        user_id = int(request.form.get("user_id"))
        new_unidade = request.form.get("unidade_id")
        new_role = request.form.get("role")

        if new_role not in ["user", "unit_admin", "secretaria", "coordenacao", "admin"]:
            return "Role inválido", 400

        # 🔴 ADMIN
        if role == "admin":
            if user_id == session["user_id"] and new_role != "admin":
                return "Você não pode remover seu próprio admin", 400

            cur.execute("""
                UPDATE usuarios
                SET unidade_id=%s, role=%s
                WHERE id=%s
            """, (new_unidade, new_role, user_id))

        # 🟡 UNIT ADMIN
        elif role == "unit_admin":

            if new_role == "admin":
                return "Sem permissão", 403

            if new_role == "unit_admin":
                return "Sem permissão", 403

            cur.execute("""
                UPDATE usuarios
                SET role=%s
                WHERE id=%s AND unidade_id=%s
            """, (new_role, user_id, unidade_id))

        db.commit()

    # ---------------- LISTAGEM ----------------
    if role == "admin":
        cur.execute("""
            SELECT id, username, role, created_at, unidade_id
            FROM usuarios
            ORDER BY id
        """)
    else:
        cur.execute("""
            SELECT id, username, role, created_at, unidade_id
            FROM usuarios
            WHERE unidade_id=%s
            ORDER BY id
        """, (unidade_id,))

    users = cur.fetchall()

    cur.execute("SELECT id, nome FROM unidades ORDER BY nome")
    unidades = cur.fetchall()

    cur.close()
    db.close()

    return render_template("admin_users.html", users=users, unidades=unidades)

    
# ---------------- DELETE USER ----------------

@app.route("/admin/delete_user/<int:id>", methods=["POST"])
def delete_user(id):
    if not is_admin():
        return "Acesso negado", 403

    if id == session["user_id"]:
        return "Você não pode se deletar", 400

    db = get_db()
    cur = db.cursor()

    cur.execute("DELETE FROM usuarios WHERE id=%s", (id,))
    db.commit()

    log_action(session["user_id"], "DELETE_USER", f"user={id}")

    cur.close()
    db.close()

    return redirect("/admin/users")

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
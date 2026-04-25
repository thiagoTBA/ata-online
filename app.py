from flask import Flask, render_template, request, redirect, session, make_response
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
from flask import make_response
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from datetime import datetime
import io


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
STATUS = {
    "PENDENTE": "Pendente",
    "EM_ATENDIMENTO": "Em atendimento",
    "AGUARDANDO_COORD": "Coordenação",
    "EM_ANALISE_COORD": "Em análise coord",
    "RETORNADO_SECRETARIA": "Retornou",
    "FINALIZADO": "Finalizado",
    "DEFERIDO": "Deferido",
    "INDEFERIDO": "Indeferido",
    "TRAMITADO": "Tramitado"
}
# ---------------- AUTH ----------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if "user_id" not in session:
        return redirect("/login")

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
                unidade_id = session.get("unidade_id")

                cur.execute("""
                    INSERT INTO usuarios (username, password, unidade_id, role)
                    VALUES (%s, %s, %s, 'user')
                """, (
                    username,
                    generate_password_hash(password),
                    unidade_id
                ))

                db.commit()
                cur.close()
                db.close()
                return redirect("/login")

        cur.close()
        db.close()

    return render_template("register.html", error=error)

# ---------------- LOGIN ----------------

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
            
            if session["role"] == "secretaria":
                return redirect("/secretaria")

            elif session["role"] == "coordenacao":
                return redirect("/coordenacao")

            elif session["role"] in ["admin", "unit_admin"]:
                return redirect("/admin/users")

            else:
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
    
    log_action(session["user_id"], "CRIAR_USUARIO", f"user={cpf}")
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
                WHERE unidade_atual_id=%s
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
    STATUS=STATUS,
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
        WHERE unidade_atual_id=%s
        ORDER BY id DESC
    """, (session["unidade_id"],))

    atas = cur.fetchall()

    # 🔥 protocolo formatado
    for a in atas:
        a["protocolo"] = formatar_protocolo(a["id"])

    # 🔥 DASHBOARD (contadores)
    stats = {
        "PENDENTE": 0,
        "EM_ATENDIMENTO": 0,
        "AGUARDANDO_COORD": 0,
        "RETORNADO_SECRETARIA": 0,
        "FINALIZADO": 0
    }

    for a in atas:
        status = a["status"]
        stats[status] = stats.get(status, 0) + 1

    cur.close()
    db.close()

    return render_template(
        "secretaria.html",
        atas=atas,
        tipos=TIPOS,
        STATUS=STATUS,
        stats=stats,  # 🔥 AQUI que entra
        role=session["role"]
    )
# ---------------- SEND ----------------

@app.route("/finalizar/<int:id>", methods=["POST"])
def finalizar(id):
    if session.get("role") not in ["admin", "secretaria"]:
        return "Sem permissão", 403

    db = get_db()
    cur = db.cursor()

    # 🔍 valida status
    cur.execute("""
        SELECT aluno_nome, status FROM atas_saida
        WHERE id=%s AND unidade_atual_id=%s
    """, (id, session["unidade_id"]))

    row = cur.fetchone()
    if not row:
        return "Protocolo não encontrado", 404

    nome, status = row

    if status not in ["EM_ATENDIMENTO", "RETORNADO_SECRETARIA"]:
        return "Não pode finalizar neste estado", 400

    # ✅ update
    cur.execute("""
        UPDATE atas_saida
        SET status='FINALIZADO'
        WHERE id=%s AND unidade_atual_id=%s
    """, (id, session["unidade_id"]))

    log_action(session["user_id"], "FINALIZOU", f"id={id} | aluno={nome}")

    db.commit()
    cur.close()
    db.close()

    return redirect("/secretaria")
#-------------------send file secret------------
@app.route("/secretaria/anexo/<int:id>", methods=["POST"])
def secretaria_anexo(id):
    if "user_id" not in session:
        return redirect("/login")

    if session.get("role") not in ["admin", "secretaria"]:
        return "Sem permissão", 403

    mensagem = request.form.get("mensagem", "").strip()
    file = request.files.get("anexo_secretaria")

    if not mensagem and not file:
        return "Envie mensagem ou anexo", 400

    if mensagem and len(mensagem) > 1000:
        return "Mensagem muito grande", 400

    db = get_db()
    cur = db.cursor()

    try:
        # 🔍 valida protocolo
        cur.execute("""
            SELECT aluno_nome, status
            FROM atas_saida
            WHERE id=%s AND unidade_atual_id=%s
        """, (id, session["unidade_id"]))

        row = cur.fetchone()
        if not row:
            return "Protocolo não encontrado", 404

        nome, status = row

        if status not in ["EM_ATENDIMENTO", "RETORNADO_SECRETARIA"]:
            return "Não pode enviar anexo neste estado", 400

        anexo_url = None

        # 📎 upload
        if file and file.filename:
            filename = file.filename.lower()

            allowed_ext = ["pdf", "png", "jpg", "jpeg"]
            ext = filename.split(".")[-1]

            if ext not in allowed_ext:
                return "Arquivo inválido", 400

            # 🔒 limite de tamanho (5MB)
            file.seek(0, os.SEEK_END)
            size = file.tell()
            file.seek(0)

            if size > 5 * 1024 * 1024:
                return "Arquivo muito grande (máx 5MB)", 400

            result = cloudinary.uploader.upload(file)
            anexo_url = result["secure_url"]

        # 🧾 update no banco
        cur.execute("""
            UPDATE atas_saida
            SET mensagem = COALESCE(mensagem, '') || %s,
                anexo_secretaria = COALESCE(%s, anexo_secretaria)
            WHERE id=%s AND unidade_atual_id=%s
        """, (
            ("\n\n" + mensagem) if mensagem else "",
            anexo_url,
            id,
            session["unidade_id"]
        ))

        db.commit()

    except Exception as e:
        db.rollback()
        return f"Erro: {e}", 500

    finally:
        cur.close()
        db.close()

    log_action(session["user_id"], "SECRETARIA_ENVIOU_ANEXO", f"id={id} | aluno={nome}")

    return redirect("/secretaria")
# ---------------- TRANSMISSÃO ----------------
@app.route("/tramitar/<int:id>", methods=["POST"])
def tramitar(id):
    if session.get("role") not in ["admin", "secretaria"]:
        return "Sem permissão", 403

    nova_unidade = request.form.get("unidade_id")

    if not nova_unidade:
        return "Unidade inválida", 400

    db = get_db()
    cur = db.cursor()

    try:
        cur.execute("""
            SELECT status FROM atas_saida
            WHERE id=%s AND unidade_atual_id=%s
        """, (id, session["unidade_id"]))

        row = cur.fetchone()
        if not row:
            return "Protocolo não encontrado", 404

        if row[0] != "EM_ATENDIMENTO":
            return "Só pode tramitar em atendimento", 400

        cur.execute("""
            UPDATE atas_saida
            SET unidade_atual_id=%s,
                status='AGUARDANDO_COORD'
            WHERE id=%s AND unidade_atual_id=%s AND status='EM_ATENDIMENTO'
        """, (nova_unidade, id, session["unidade_id"]))

        db.commit()

    except:
        db.rollback()
        return "Erro ao tramitar", 500

    finally:
        cur.close()
        db.close()
    
    log_action(session["user_id"], "TRAMITOU", f"id={id} -> unidade={nova_unidade}")
    return redirect("/secretaria")
# ---------------- COORDENAÇÃO ----------------
@app.route("/coordenacao")
def coordenacao():
    if session.get("role") not in ["coordenacao", "admin"]:
        return redirect("/")

    db = get_db()
    cur = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT * FROM atas_saida
        WHERE unidade_atual_id=%s
        AND status IN ('AGUARDANDO_COORD','RETORNADO_SECRETARIA')
        ORDER BY id DESC
    """, (session["unidade_id"],))

    atas = cur.fetchall()

    for a in atas:
        a["protocolo"] = formatar_protocolo(a["id"])

    return render_template(
    "coordenacao.html",
    atas=atas,
    tipos=TIPOS,
    STATUS=STATUS,
    role=session["role"]
)
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
    status = "PENDENTE"

    db = get_db()
    cur = db.cursor()

    cur.execute("""
    INSERT INTO atas_saida
    (aluno_nome, cpf, email, telefone, curso,
     tipo, justificativa, status,
     anexo_url,
     rg, sexo, turno, municipio, projeto,
     usuario_id, unidade_id,
     unidade_origem_id, unidade_atual_id)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
""", (
    aluno_nome, cpf, email, telefone, curso,
    tipo, justificativa, status,
    anexo_url,
    rg, sexo, turno, municipio, projeto,
    session["user_id"], session["unidade_id"],
    session["unidade_id"], session["unidade_id"]
))

    db.commit()
    cur.close()
    db.close()
    log_action(session["user_id"], "CRIAR_REQUERIMENTO", f"aluno={aluno_nome}")

    return redirect("/")

# ---------------- ATENDI ----------
@app.route("/atender/<int:id>", methods=["POST"])
def atender(id):
    if "user_id" not in session:
        return redirect("/login")

    if session.get("role") not in ["admin", "secretaria"]:
        return "Sem permissão", 403

    mensagem = request.form.get("mensagem", "").strip()

    if len(mensagem) > 1000:
        return "Mensagem muito grande", 400

    db = get_db()
    cur = db.cursor()

    try:
        cur.execute("""
            SELECT aluno_nome FROM atas_saida
            WHERE id=%s AND unidade_atual_id=%s AND status='PENDENTE'
        """, (id, session["unidade_id"]))

        row = cur.fetchone()
        if not row:
            return "Protocolo inválido ou já atendido", 400

        nome = row[0]

        cur.execute("""
            UPDATE atas_saida
            SET atendente=%s,
                data_atendimento=NOW(),
                mensagem=%s,
                status='EM_ATENDIMENTO'
            WHERE id=%s AND unidade_atual_id=%s AND status='PENDENTE'
        """, (
            session["username"],
            mensagem,
            id,
            session["unidade_id"]
        ))

        db.commit()

    except:
        db.rollback()
        return "Erro ao atender", 500

    finally:
        cur.close()
        db.close()

    log_action(session["user_id"], "ATENDEU", f"id={id} | aluno={nome}")

    return redirect("/secretaria")
# ---------------- PARECER ----------------
@app.route("/parecer/<int:id>", methods=["POST"])
def parecer(id):
    if "user_id" not in session:
        return redirect("/login")

    if session.get("role") not in ["admin", "coordenacao"]:
        return "Sem permissão", 403

    parecer = request.form.get("parecer", "").strip()
    decisao = request.form.get("status")

    if not parecer:
        return "Parecer obrigatório", 400

    if len(parecer) > 2000:
        return "Parecer muito grande", 400

    db = get_db()
    cur = db.cursor()

    try:
        cur.execute("""
            SELECT status FROM atas_saida
            WHERE id=%s AND unidade_atual_id=%s
        """, (id, session["unidade_id"]))

        row = cur.fetchone()
        if not row:
            return "Protocolo não encontrado", 404

        if row[0] != "AGUARDANDO_COORD":
            return "Protocolo não está na coordenação", 400

        file = request.files.get("anexo_coord")
        anexo_coord = None

        # 📎 upload com validação
        if file and file.filename:
            filename = file.filename.lower()

            allowed_ext = ["pdf", "png", "jpg", "jpeg"]
            ext = filename.split(".")[-1]

            if ext not in allowed_ext:
                return "Arquivo inválido", 400

            # 🔒 limite 5MB
            file.seek(0, os.SEEK_END)
            size = file.tell()
            file.seek(0)

            if size > 5 * 1024 * 1024:
                return "Arquivo muito grande (máx 5MB)", 400

            result = cloudinary.uploader.upload(file)
            anexo_coord = result["secure_url"]

        # 🧾 update
        if anexo_coord:
            cur.execute("""
                UPDATE atas_saida
                SET parecer=%s,
                    decisao=%s,
                    anexo_coord=%s,
                    coordenador=%s,
                    data_parecer=NOW(),
                    status='RETORNADO_SECRETARIA'
                WHERE id=%s AND unidade_atual_id=%s AND status='AGUARDANDO_COORD'
            """, (
                parecer,
                decisao,
                anexo_coord,
                session["username"],
                id,
                session["unidade_id"]
            ))

        else:
            cur.execute("""
                UPDATE atas_saida
                SET parecer=%s,
                    decisao=%s,
                    coordenador=%s,
                    data_parecer=NOW(),
                    status='RETORNADO_SECRETARIA'
                WHERE id=%s AND unidade_atual_id=%s AND status='AGUARDANDO_COORD'
            """, (
                parecer,
                decisao,
                session["username"],
                id,
                session["unidade_id"]
            ))

        db.commit()
        log_action(session["user_id"], "PARECER", f"id={id} | {decisao}")

    except Exception as e:
        db.rollback()
        return f"Erro ao registrar parecer: {e}", 500

    finally:
        cur.close()
        db.close()

    return redirect("/coordenacao")

# ---------------- AUDITORIA ---------------
@app.route("/admin/logs_unidade")
def logs_unidade():
    if "user_id" not in session:
        return redirect("/login")

    if session.get("role") not in ["admin", "unit_admin"]:
        return "Sem permissão", 403

    db = get_db()
    cur = db.cursor()

    # 🔥 pega logs só da unidade do admin
    cur.execute("""
        SELECT l.acao, l.detalhes, l.criado_em, u.username
        FROM logs l
        JOIN usuarios u ON u.id = l.user_id
        WHERE u.unidade_id = %s
        ORDER BY l.criado_em DESC
        LIMIT 200
    """, (session["unidade_id"],))

    logs = [
        {
            "acao": r[0],
            "detalhes": r[1],
            "criado_em": r[2],
            "username": r[3]
        }
        for r in cur.fetchall()
    ]

    cur.close()
    db.close()

    return render_template("logs_unidade.html", logs=logs)
# ---------------- LOG ADM GLOBBAL ---------------
@app.route("/admin/logs")
def logs_admin():
    if "user_id" not in session:
        return redirect("/login")

    if session.get("role") != "admin":
        return "Sem permissão", 403

    db = get_db()
    cur = db.cursor()

    cur.execute("""
        SELECT l.acao, l.detalhes, l.criado_em, u.username, un.nome
        FROM logs l
        LEFT JOIN usuarios u ON u.id = l.user_id
        LEFT JOIN unidades un ON un.id = u.unidade_id
        ORDER BY l.criado_em DESC
        LIMIT 300
    """)

    logs = [
        {
            "acao": r[0],
            "detalhes": r[1],
            "criado_em": r[2],
            "username": r[3],
            "unidade": r[4] or "Sem unidade"
        }
        for r in cur.fetchall()
    ]

    cur.close()
    db.close()

    return render_template("logs_admin.html", logs=logs)
# ---------------- protocolos ---------------
@app.route("/admin/protocolos")
def protocolos_unidade():
    if "user_id" not in session:
        return redirect("/login")

    if session.get("role") not in ["admin", "unit_admin"]:
        return "Sem permissão", 403

    db = get_db()
    cur = db.cursor()

    if session["role"] == "admin":
        cur.execute("SELECT * FROM atas_saida ORDER BY criado_em DESC")
    else:
        cur.execute("""
            SELECT * FROM atas_saida
            WHERE unidade_id = %s
            ORDER BY criado_em DESC
        """, (session["unidade_id"],))

    atas = cur.fetchall()

    cur.close()
    db.close()

    return render_template("protocolos.html", atas=atas)
# ---------------- gerar PDF ---------------


def header_footer(canvas, doc):
    canvas.saveState()

    # 🔥 Cabeçalho
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawString(2 * cm, 28 * cm, "SISTEMA ATA ONLINE")

    canvas.setFont("Helvetica", 8)
    canvas.drawString(2 * cm, 27.5 * cm, f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}")

    # 🔥 Rodapé
    canvas.setFont("Helvetica", 8)
    canvas.drawString(2 * cm, 1.5 * cm, f"Página {doc.page}")

    canvas.restoreState()


@app.route("/admin/protocolos/pdf", methods=["POST"])
def gerar_pdf_protocolos():
    if "user_id" not in session:
        return redirect("/login")

    ids = request.form.getlist("ids")
    if not ids:
        return "Nenhum protocolo selecionado"

    db = get_db()
    cur = db.cursor()

    query = f"""
        SELECT a.*, u.nome
        FROM atas_saida a
        LEFT JOIN unidades u ON u.id = a.unidade_id
        WHERE a.id IN ({','.join(['%s'] * len(ids))})
        ORDER BY a.criado_em DESC
    """
    cur.execute(query, ids)
    dados = cur.fetchall()

    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=3 * cm,
        bottomMargin=2 * cm
    )

    styles = getSampleStyleSheet()

    titulo = ParagraphStyle(
        "Titulo",
        parent=styles["Heading1"],
        alignment=1,
        spaceAfter=15
    )

    normal = styles["Normal"]

    caixa = ParagraphStyle(
        "Caixa",
        parent=styles["Normal"],
        backColor="#f3f4f6",
        borderPadding=6,
        spaceAfter=10
    )

    elements = []

    for i, a in enumerate(dados):

        # 🔥 Título do protocolo
        elements.append(Paragraph(f"PROTOCOLO Nº {a[0]}", titulo))

        elements.append(Paragraph(f"<b>Unidade:</b> {a[-1] or 'N/A'}", normal))
        elements.append(Spacer(1, 10))

        # 🔥 Dados do aluno
        elements.append(Paragraph("<b>DADOS DO ALUNO</b>", styles["Heading3"]))
        elements.append(Paragraph(f"Nome: {a[1]}", normal))
        elements.append(Paragraph(f"CPF: {a[2]}", normal))
        elements.append(Paragraph(f"Email: {a[3]}", normal))
        elements.append(Paragraph(f"Telefone: {a[4]}", normal))

        elements.append(Spacer(1, 10))

        # 🔥 Dados acadêmicos
        elements.append(Paragraph("<b>DADOS ACADÊMICOS</b>", styles["Heading3"]))
        elements.append(Paragraph(f"Curso: {a[5]}", normal))
        elements.append(Paragraph(f"Turno: {a[16]}", normal))
        elements.append(Paragraph(f"Município: {a[18]}", normal))

        elements.append(Spacer(1, 10))

        # 🔥 Justificativa
        elements.append(Paragraph("<b>JUSTIFICATIVA</b>", styles["Heading3"]))
        elements.append(Paragraph(a[6] or "-", caixa))

        # 🔥 Status
        elements.append(Paragraph(f"<b>Status:</b> {a[8]}", normal))

        if a[15]:
            elements.append(Paragraph(f"<b>Decisão:</b> {a[15]}", normal))

        if a[13]:
            elements.append(Spacer(1, 5))
            elements.append(Paragraph("<b>PARECER DA COORDENAÇÃO</b>", styles["Heading3"]))
            elements.append(Paragraph(a[13], caixa))

        elements.append(Spacer(1, 30))

        # 🔥 Assinatura
        elements.append(Paragraph("______________________________", normal))
        elements.append(Paragraph("Responsável", normal))

        # 🔥 quebra de página
        if i < len(dados) - 1:
            elements.append(PageBreak())

    doc.build(elements, onFirstPage=header_footer, onLaterPages=header_footer)

    buffer.seek(0)

    response = make_response(buffer.read())
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = "attachment; filename=protocolos_oficial.pdf"

    return response

# ---------------- ANEXO ---------------
@app.route("/coord_tramitar/<int:id>", methods=["POST"])
def coord_tramitar(id):
    if session.get("role") not in ["admin", "coordenacao"]:
        return "Sem permissão", 403

    nova_unidade = request.form.get("unidade_id")

    if not nova_unidade:
        return "Unidade inválida", 400

    db = get_db()
    cur = db.cursor()

    try:
        cur.execute("""
            SELECT status FROM atas_saida
            WHERE id=%s AND unidade_atual_id=%s
        """, (id, session["unidade_id"]))

        row = cur.fetchone()
        if not row:
            return "Protocolo inválido", 404

        if row[0] not in ["AGUARDANDO_COORD", "RETORNADO_SECRETARIA"]:
            return "Não pode tramitar neste estado", 400

        cur.execute("""
            UPDATE atas_saida
            SET unidade_atual_id=%s,
                status='AGUARDANDO_COORD'
            WHERE id=%s AND unidade_atual_id=%s
        """, (nova_unidade, id, session["unidade_id"]))

        db.commit()

    except:
        db.rollback()
        return "Erro ao tramitar", 500

    finally:
        cur.close()
        db.close()

    log_action(session["user_id"], "COORD_TRAMITOU", f"id={id}")

    return redirect("/coordenacao")
# ---------------- admin supa ----------------
@app.route("/admin/create_full_user", methods=["POST"])
def create_full_user():
    if session.get("role") not in ["admin", "unit_admin"]:
        return "Sem permissão", 403

    username = request.form.get("username")
    unidade_id = request.form.get("unidade_id")
    role = request.form.get("role")

    if not username or not unidade_id or not role:
        return "Dados inválidos", 400

    if session["role"] == "unit_admin":
        unidade_id = session["unidade_id"]

        if role in ["admin", "unit_admin"]:
            return "Sem permissão", 403

    senha = gerar_senha()

    db = get_db()
    cur = db.cursor()

    try:
        cur.execute("""
            INSERT INTO usuarios (username, password, unidade_id, role)
            VALUES (%s, %s, %s, %s)
        """, (
            username,
            generate_password_hash(senha),
            unidade_id,
            role
        ))

        db.commit()

    except:
        db.rollback()
        return "Erro ao criar usuário", 500

    finally:
        cur.close()
        db.close()

    log_action(session["user_id"], "CRIAR_USUARIO", f"user={username}")
    return f"""
    <script>
    alert("Usuário criado!\\nLogin: {username}\\nSenha: {senha}");
    window.location.href="/admin/users";
    </script>
    """
# ---------------- ENVIAR UNIDADES ----------------

@app.route("/enviar_coord/<int:id>", methods=["POST"])
def enviar_coord(id):
    if session.get("role") not in ["admin", "secretaria"]:
        return "Sem permissão", 403

    db = get_db()
    cur = db.cursor()

    # 🔍 valida status
    cur.execute("""
        SELECT aluno_nome, status FROM atas_saida
        WHERE id=%s AND unidade_atual_id=%s
    """, (id, session["unidade_id"]))

    row = cur.fetchone()
    if not row:
        return "Protocolo não encontrado", 404

    nome, status = row

    if status != "EM_ATENDIMENTO":
        return "Só pode enviar para coord após atendimento", 400

    # ✅ update
    cur.execute("""
        UPDATE atas_saida
        SET status='AGUARDANDO_COORD'
        WHERE id=%s AND unidade_atual_id=%s
    """, (id, session["unidade_id"]))

    log_action(session["user_id"], "ENVIOU_COORD", f"id={id} | aluno={nome}")

    db.commit()
    cur.close()
    db.close()
    

    return redirect("/secretaria")

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
            log_action(session["user_id"], "CRIAR_UNIDADE", f"nome={nome}")
        except:
            return "Unidade já existe"

    cur.execute("SELECT id, nome FROM unidades ORDER BY nome")
    unidades = cur.fetchall()

    cur.close()
    db.close()

    return render_template("unidades.html", unidades=unidades)

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

        if role == "admin":
            if user_id == session["user_id"] and new_role != "admin":
                return "Não pode remover seu admin", 400

            cur.execute("""
                UPDATE usuarios
                SET unidade_id=%s, role=%s
                WHERE id=%s
            """, (new_unidade, new_role, user_id))

        elif role == "unit_admin":
            if new_role in ["admin", "unit_admin"]:
                return "Sem permissão", 403

            cur.execute("""
                UPDATE usuarios
                SET role=%s
                WHERE id=%s AND unidade_id=%s
            """, (new_role, user_id, unidade_id))

        
        db.commit()

    # ---------------- FILTROS ----------------
    q = request.args.get("q")
    role_f = request.args.get("role")
    unidade_f = request.args.get("unidade")

    query = """
        SELECT id, username, role, created_at, unidade_id
        FROM usuarios
        WHERE 1=1
    """
    params = []

    if role == "unit_admin":
        query += " AND unidade_id=%s"
        params.append(unidade_id)

    if q:
        query += " AND username ILIKE %s"
        params.append(f"%{q}%")

    if role_f:
        query += " AND role=%s"
        params.append(role_f)

    if unidade_f and role == "admin":
        query += " AND unidade_id=%s"
        params.append(unidade_f)

    query += " ORDER BY id DESC"

    cur.execute(query, tuple(params))
    users = cur.fetchall()

    cur.execute("SELECT id, nome FROM unidades ORDER BY nome")
    unidades = cur.fetchall()

    cur.close()
    db.close()

    return render_template("admin_users.html", users=users, unidades=unidades)

# ---------------- RESERT ADM ----------------
@app.route("/admin/reset_password/<int:id>", methods=["POST"])
def reset_password(id):
    if session.get("role") not in ["admin", "unit_admin"]:
        return "Sem permissão", 403

    db = get_db()
    cur = db.cursor()

    # 🔒 unit_admin só da unidade dele
    if session["role"] == "unit_admin":
        cur.execute("SELECT unidade_id FROM usuarios WHERE id=%s", (id,))
        u = cur.fetchone()
        if not u or u[0] != session["unidade_id"]:
            return "Sem permissão", 403

    nova = gerar_senha()

    cur.execute("""
        UPDATE usuarios
        SET password=%s
        WHERE id=%s
    """, (generate_password_hash(nova), id))

    db.commit()
    cur.close()
    db.close()

    return f"""
<script>
alert("Nova senha: {nova}");
window.location.href="/admin/users";
</script>
"""
# ---------------- TROCA SENHA USER ----------------
@app.route("/change_password", methods=["POST"])
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
  
# ---------------- DELETE unidade ----------------
@app.route("/admin/delete_unidade/<int:id>", methods=["POST"])
def delete_unidade(id):
    if not is_admin():
        return "Acesso negado", 403

    db = get_db()
    cur = db.cursor()

    try:
        cur.execute("DELETE FROM unidades WHERE id=%s", (id,))
        db.commit()

        log_action(session["user_id"], "DELETE_UNIDADE", f"id={id}")

    except Exception as e:
        db.rollback()
        return f"Erro ao excluir: {e}", 500

    finally:
        cur.close()
        db.close()

    return redirect("/admin/unidades")
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
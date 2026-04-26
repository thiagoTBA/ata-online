from flask import Blueprint, request, redirect, session, render_template
from werkzeug.security import generate_password_hash
from services.db import get_db
from services.utils import log_action, gerar_senha, is_admin

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


# ---------------- CREATE USER SIMPLES ----------------
@admin_bp.route("/create_user", methods=["POST"])
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

    return f"""
    <h2>Usuário criado</h2>
    <p><b>Login:</b> {cpf}</p>
    <p><b>Senha:</b> {senha}</p>
    <a href="/">Voltar</a>
    """


# ---------------- CREATE USER COMPLETO ----------------
@admin_bp.route("/create_full_user", methods=["POST"])
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


# ---------------- UNIDADES ----------------
@admin_bp.route("/unidades", methods=["GET", "POST"])
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


# ---------------- USERS ----------------
@admin_bp.route("/users", methods=["GET", "POST"])
def admin_users():
    if "user_id" not in session:
        return redirect("/login")

    role = session.get("role")
    unidade_id = session.get("unidade_id")

    if role not in ["admin", "unit_admin"]:
        return "Acesso negado", 403

    db = get_db()
    cur = db.cursor()

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


# ---------------- RESET PASSWORD ----------------
@admin_bp.route("/reset_password/<int:id>", methods=["POST"])
def reset_password(id):
    if session.get("role") not in ["admin", "unit_admin"]:
        return "Sem permissão", 403

    db = get_db()
    cur = db.cursor()

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


# ---------------- DELETE UNIDADE ----------------
@admin_bp.route("/delete_unidade/<int:id>", methods=["POST"])
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
@admin_bp.route("/delete_user/<int:id>", methods=["POST"])
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


# ---------------- LOGS UNIDADE ----------------
@admin_bp.route("/logs_unidade")
def logs_unidade():
    if "user_id" not in session:
        return redirect("/login")

    if session.get("role") not in ["admin", "unit_admin"]:
        return "Sem permissão", 403

    db = get_db()
    cur = db.cursor()

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


# ---------------- LOGS ADMIN ----------------
@admin_bp.route("/logs")
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


# ---------------- PROTOCOLOS ----------------
@admin_bp.route("/protocolos")
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


# ---------------- PROTOCOLOS PDF ----------------
@admin_bp.route("/protocolos/pdf", methods=["POST"])
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

    import io
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from flask import make_response

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

        elements.append(Paragraph(f"PROTOCOLO Nº {a[0]}", titulo))
        elements.append(Paragraph(f"<b>Unidade:</b> {a[-1] or 'N/A'}", normal))
        elements.append(Spacer(1, 10))

        elements.append(Paragraph("<b>DADOS DO ALUNO</b>", styles["Heading3"]))
        elements.append(Paragraph(f"Nome: {a[1]}", normal))
        elements.append(Paragraph(f"CPF: {a[2]}", normal))
        elements.append(Paragraph(f"Email: {a[3]}", normal))
        elements.append(Paragraph(f"Telefone: {a[4]}", normal))

        elements.append(Spacer(1, 10))

        elements.append(Paragraph("<b>DADOS ACADÊMICOS</b>", styles["Heading3"]))
        elements.append(Paragraph(f"Curso: {a[5]}", normal))
        elements.append(Paragraph(f"Turno: {a[16]}", normal))
        elements.append(Paragraph(f"Município: {a[18]}", normal))

        elements.append(Spacer(1, 10))

        elements.append(Paragraph("<b>JUSTIFICATIVA</b>", styles["Heading3"]))
        elements.append(Paragraph(a[6] or "-", caixa))

        elements.append(Paragraph(f"<b>Status:</b> {a[8]}", normal))

        if a[15]:
            elements.append(Paragraph(f"<b>Decisão:</b> {a[15]}", normal))

        if a[13]:
            elements.append(Spacer(1, 5))
            elements.append(Paragraph("<b>PARECER DA COORDENAÇÃO</b>", styles["Heading3"]))
            elements.append(Paragraph(a[13], caixa))

        elements.append(Spacer(1, 30))

        elements.append(Paragraph("______________________________", normal))
        elements.append(Paragraph("Responsável", normal))

        if i < len(dados) - 1:
            elements.append(PageBreak())

    doc.build(elements)

    buffer.seek(0)

    response = make_response(buffer.read())
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = "attachment; filename=protocolos_oficial.pdf"

    return response
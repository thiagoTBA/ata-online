from flask import Blueprint, render_template, request, redirect, session
import psycopg2.extras

from services.db import get_db
from services.utils import formatar_protocolo, log_action

main_bp = Blueprint("main", __name__)


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


# ---------------- INDEX ----------------
@main_bp.route("/")
def index():
    if "user_id" not in session:
        return redirect("/login")

    role = session.get("role")
    unidade_id = session.get("unidade_id")
    user_id = session.get("user_id")

    db = get_db()
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


# ---------------- ADD ----------------
@main_bp.route("/add", methods=["POST"])
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

    file = request.files.get("anexo")
    anexo_url = None

    allowed = (".pdf", ".png", ".jpg", ".jpeg")

    if file and file.filename:
        filename = file.filename.lower()

        if not filename.endswith(allowed):
            return "Arquivo inválido"

        file.seek(0, 2)
        size = file.tell()
        file.seek(0)

        if size > 5 * 1024 * 1024:
            return "Arquivo muito grande (máx 5MB)"

        import cloudinary.uploader
        result = cloudinary.uploader.upload(file)
        anexo_url = result["secure_url"]

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


from services.pdf import gerar_pdf_processo_buffer, build_response


@main_bp.route("/processo/<int:id>/pdf")
def processo_pdf(id):
    if "user_id" not in session:
        return redirect("/login")

    db = get_db()
    cur = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("SELECT * FROM atas_saida WHERE id=%s", (id,))
    ata = cur.fetchone()

    cur.close()
    db.close()

    if not ata:
        return "Não encontrado", 404

    buffer = gerar_pdf_processo_buffer(ata)

    return build_response(buffer, f"processo_{id}.pdf")
from flask import Blueprint, render_template, request, redirect, session
import psycopg2.extras
import os
from routes.main import STATUS
from services.db import get_db
from services.utils import formatar_protocolo, log_action

secretaria_bp = Blueprint("secretaria", __name__)


# ---------------- SECRETARIA ----------------
@secretaria_bp.route("/secretaria")
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

    for a in atas:
        a["protocolo"] = formatar_protocolo(a["id"])

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
        tipos=None,
        stats=stats,
        role=session["role"]
    )


# ---------------- ATENDER ----------------
@secretaria_bp.route("/atender/<int:id>", methods=["POST"])
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


# ---------------- FINALIZAR ----------------
@secretaria_bp.route("/finalizar/<int:id>", methods=["POST"])
def finalizar(id):
    if session.get("role") not in ["admin", "secretaria"]:
        return "Sem permissão", 403

    db = get_db()
    cur = db.cursor()

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


# ---------------- ANEXO SECRETARIA ----------------
@secretaria_bp.route("/secretaria/anexo/<int:id>", methods=["POST"])
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

        if file and file.filename:
            filename = file.filename.lower()
            ext = filename.split(".")[-1]

            if ext not in ["pdf", "png", "jpg", "jpeg"]:
                return "Arquivo inválido", 400

            file.seek(0, os.SEEK_END)
            size = file.tell()
            file.seek(0)

            if size > 5 * 1024 * 1024:
                return "Arquivo muito grande (máx 5MB)", 400

            import cloudinary.uploader
            result = cloudinary.uploader.upload(file)
            anexo_url = result["secure_url"]

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


# ---------------- TRAMITAR ----------------
@secretaria_bp.route("/tramitar/<int:id>", methods=["POST"])
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


# ---------------- ENVIAR COORD ----------------
@secretaria_bp.route("/enviar_coord/<int:id>", methods=["POST"])
def enviar_coord(id):
    if session.get("role") not in ["admin", "secretaria"]:
        return "Sem permissão", 403

    db = get_db()
    cur = db.cursor()

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
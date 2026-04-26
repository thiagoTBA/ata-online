from flask import Blueprint, render_template, request, redirect, session
import psycopg2.extras
from routes.main import STATUS
from services.db import get_db
from services.utils import log_action, formatar_protocolo
from routes.main import STATUS

coordenacao_bp = Blueprint("coordenacao", __name__)


# ---------------- COORDENAÇÃO ----------------
@coordenacao_bp.route("/coordenacao")
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

    cur.execute("""
        SELECT status, COUNT(*) as total
        FROM atas_saida
        WHERE unidade_atual_id=%s
        GROUP BY status
    """, (session["unidade_id"],))

    stats = {
        "PENDENTE": 0,
        "EM_ATENDIMENTO": 0,
        "AGUARDANDO_COORD": 0,
        "RETORNADO_SECRETARIA": 0,
        "FINALIZADO": 0
    }

    for row in cur.fetchall():
        stats[row["status"]] = row["total"]

    cur.close()
    db.close()

    return render_template(
        "coordenacao.html",
        atas=atas,
        tipos=None,
        STATUS=STATUS,
        stats=stats,
        role=session["role"]
    )


# ---------------- PARECER ----------------
@coordenacao_bp.route("/parecer/<int:id>", methods=["POST"])
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

        if file and file.filename:
            filename = file.filename.lower()

            allowed_ext = ["pdf", "png", "jpg", "jpeg"]
            ext = filename.split(".")[-1]

            if ext not in allowed_ext:
                return "Arquivo inválido", 400

            file.seek(0, 2)
            size = file.tell()
            file.seek(0)

            if size > 5 * 1024 * 1024:
                return "Arquivo muito grande (máx 5MB)", 400

            import cloudinary.uploader
            result = cloudinary.uploader.upload(file)
            anexo_coord = result["secure_url"]

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


# ---------------- COORD TRAMITAR ----------------
@coordenacao_bp.route("/coord_tramitar/<int:id>", methods=["POST"])
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
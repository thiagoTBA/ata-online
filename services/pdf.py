from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from flask import make_response
from io import BytesIO


def safe(v):
    return str(v) if v is not None else "-"


def gerar_pdf_processo_buffer(ata):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer)

    styles = getSampleStyleSheet()
    elements = []

    # 🔥 TÍTULO
    elements.append(Paragraph("PROCESSO DO ALUNO", styles["Title"]))
    elements.append(Spacer(1, 12))

    # 🔥 IDENTIFICAÇÃO
    elements.append(Paragraph("Protocolo: " + safe(ata.get("numero_requerimento")), styles["Normal"]))
    elements.append(Paragraph("Aluno: " + safe(ata.get("aluno_nome")), styles["Normal"]))
    elements.append(Paragraph("CPF: " + safe(ata.get("cpf")), styles["Normal"]))
    elements.append(Paragraph("Email: " + safe(ata.get("email")), styles["Normal"]))
    elements.append(Paragraph("Telefone: " + safe(ata.get("telefone")), styles["Normal"]))
    elements.append(Spacer(1, 10))

    # 🔥 DADOS ACADÊMICOS
    elements.append(Paragraph("Curso: " + safe(ata.get("curso")), styles["Normal"]))
    elements.append(Paragraph("Turno: " + safe(ata.get("turno")), styles["Normal"]))
    elements.append(Paragraph("Projeto: " + safe(ata.get("projeto")), styles["Normal"]))
    elements.append(Paragraph("Município: " + safe(ata.get("municipio")), styles["Normal"]))
    elements.append(Spacer(1, 10))

    # 🔥 SOLICITAÇÃO
    elements.append(Paragraph("Tipo: " + safe(ata.get("tipo")), styles["Normal"]))
    elements.append(Paragraph("Justificativa:", styles["Heading3"]))
    elements.append(Paragraph(safe(ata.get("justificativa")), styles["Normal"]))
    elements.append(Spacer(1, 10))

    # 🔥 SECRETARIA
    elements.append(Paragraph("Atendimento da Secretaria:", styles["Heading3"]))
    elements.append(Paragraph("Atendente: " + safe(ata.get("atendente")), styles["Normal"]))
    elements.append(Paragraph("Mensagem: " + safe(ata.get("mensagem")), styles["Normal"]))
    elements.append(Spacer(1, 10))

    # 🔥 COORDENAÇÃO
    elements.append(Paragraph("Análise da Coordenação:", styles["Heading3"]))
    elements.append(Paragraph("Coordenador: " + safe(ata.get("coordenador")), styles["Normal"]))
    elements.append(Paragraph("Parecer: " + safe(ata.get("parecer")), styles["Normal"]))
    elements.append(Paragraph("Decisão: " + safe(ata.get("decisao")), styles["Normal"]))
    elements.append(Spacer(1, 10))

    # 🔥 STATUS FINAL
    elements.append(Paragraph("Status Final: " + safe(ata.get("status")), styles["Heading2"]))

    # 🔥 ANEXOS
    elements.append(Spacer(1, 10))
    elements.append(Paragraph("Anexos:", styles["Heading3"]))
    elements.append(Paragraph("Aluno: " + safe(ata.get("anexo_url")), styles["Normal"]))
    elements.append(Paragraph("Secretaria: " + safe(ata.get("anexo_secretaria")), styles["Normal"]))
    elements.append(Paragraph("Coordenação: " + safe(ata.get("anexo_coord")), styles["Normal"]))

    doc.build(elements)
    buffer.seek(0)

    return buffer


def build_response(buffer, filename):
    response = make_response(buffer.read())
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = f"inline; filename={filename}"
    return response
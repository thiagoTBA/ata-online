from datetime import datetime
from flask import session
from .db import get_db
import random, string

def formatar_protocolo(numero):
    ano = datetime.now().year
    return f"CETAM-{ano}-{str(numero).zfill(6)}"

def is_admin():
    return session.get("role") == "admin"

def gerar_senha(tamanho=6):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=tamanho))

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
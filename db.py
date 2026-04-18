import sqlite3

conn = sqlite3.connect("db.sqlite3")

conn.execute("""
CREATE TABLE usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE,
    password TEXT
)
""")

conn.execute("""
CREATE TABLE atas_saida (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    destinatario TEXT,
    descricao TEXT,
    responsavel TEXT,
    status TEXT DEFAULT 'pendente',
    data TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    imagem TEXT,
    usuario_id INTEGER
)
""")

conn.commit()
conn.close()

print("Banco criado!")
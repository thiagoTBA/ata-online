import sqlite3

conn = sqlite3.connect("db.sqlite3")

conn.execute("ALTER TABLE atas_saida ADD COLUMN imagem TEXT")

conn.commit()
conn.close()

print("Coluna adicionada!")
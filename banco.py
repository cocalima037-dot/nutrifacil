import sqlite3


def criar_banco():
    conn = sqlite3.connect('dieta.db')
    cursor = conn.cursor()

    # Tabela de refeições
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS refeicoes
                   (
                       id
                       INTEGER
                       PRIMARY
                       KEY
                       AUTOINCREMENT,
                       alimento
                       TEXT,
                       peso_g
                       REAL,
                       proteina_g
                       REAL,
                       carboidrato_g
                       REAL,
                       gordura_g
                       REAL,
                       calorias
                       REAL,
                       data
                       DATE
                       DEFAULT
                       CURRENT_DATE
                   )
                   ''')

    # Tabela de usuários
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS usuarios
                   (
                       id
                       INTEGER
                       PRIMARY
                       KEY
                       AUTOINCREMENT,
                       usuario
                       TEXT
                       UNIQUE
                       NOT
                       NULL,
                       senha
                       TEXT
                       NOT
                       NULL,
                       api_key
                       TEXT
                   )
                   ''')

    conn.commit()
    conn.close()
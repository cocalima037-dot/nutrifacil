import sys
import asyncio
import os
import re
from PIL import Image

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
from google import genai
import extra_streamlit_components as stx
from banco import criar_banco

# Inicializa o banco de dados
criar_banco()

st.set_page_config(page_title="NutriIA - Chat & Dieta", page_icon="🥗", layout="wide")

# ---------------------------------------------------------
# GERENCIADOR DE LOCALSTORAGE (PERSISTÊNCIA DE LOGIN)
# ---------------------------------------------------------
cookie_manager = stx.CookieManager()


# ---------------------------------------------------------
# FUNÇÕES DE AUTENTICAÇÃO E BANCO DE DADOS
# ---------------------------------------------------------
def cadastrar_usuario(usuario, senha, api_key):
    try:
        conn = sqlite3.connect('dieta.db')
        cursor = conn.cursor()
        cursor.execute("INSERT INTO usuarios (usuario, senha, api_key) VALUES (?, ?, ?)", (usuario, senha, api_key))
        conn.commit()
        conn.close()
        return True, "Usuário cadastrado com sucesso!"
    except sqlite3.IntegrityError:
        return False, "Nome de usuário já existe!"
    except Exception as e:
        return False, f"Erro ao cadastrar: {e}"


def validar_login(usuario, senha):
    conn = sqlite3.connect('dieta.db')
    cursor = conn.cursor()
    cursor.execute("SELECT usuario, api_key FROM usuarios WHERE usuario = ? AND senha = ?", (usuario, senha))
    user = cursor.fetchone()
    conn.close()
    return user


def atualizar_api_key_bd(usuario, api_key):
    conn = sqlite3.connect('dieta.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE usuarios SET api_key = ? WHERE usuario = ?", (api_key, usuario))
    conn.commit()
    conn.close()


def zerar_banco_refeicoes():
    """Remove todas as refeições do banco de dados SQLite."""
    conn = sqlite3.connect('dieta.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM refeicoes")
    conn.commit()
    conn.close()


# ---------------------------------------------------------
# VERIFICAÇÃO DE SESSÃO / LOCALSTORAGE
# ---------------------------------------------------------
saved_user = cookie_manager.get(cookie="nutri_user")
saved_pass = cookie_manager.get(cookie="nutri_pass")
saved_api = cookie_manager.get(cookie="nutri_api")

if "autenticado" not in st.session_state:
    if saved_user and saved_pass:
        user_data = validar_login(saved_user, saved_pass)
        if user_data:
            st.session_state.autenticado = True
            st.session_state.usuario_logado = saved_user
            st.session_state.api_key = saved_api if saved_api else user_data[1]
        else:
            st.session_state.autenticado = False
    else:
        st.session_state.autenticado = False

# ---------------------------------------------------------
# TELA DE LOGIN / CADASTRO (EXIBIDA SE NÃO AUTENTICADO)
# ---------------------------------------------------------
if not st.session_state.autenticado:
    st.title("🍽 Nutrifacil")

    tab_login, tab_cadastro = st.tabs(["🔑 Entrar", "📝 Criar Conta"])

    with tab_login:
        with st.form("form_login"):
            usuario_input = st.text_input("Usuário")
            senha_input = st.text_input("Senha", type="password")
            lembrar = st.checkbox("Lembrar de mim (Manter conectado)", value=True)
            btn_entrar = st.form_submit_button("Entrar")

            if btn_entrar:
                user_data = validar_login(usuario_input, senha_input)
                if user_data:
                    st.session_state.autenticado = True
                    st.session_state.usuario_logado = user_data[0]
                    st.session_state.api_key = user_data[1]

                    if lembrar:
                        cookie_manager.set("nutri_user", user_data[0], key="set_u")
                        cookie_manager.set("nutri_pass", senha_input, key="set_p")
                        cookie_manager.set("nutri_api", user_data[1] or "", key="set_a")

                    st.success("Login efetuado com sucesso!")
                    st.rerun()
                else:
                    st.error("Usuário ou senha incorretos.")

    with tab_cadastro:
        with st.form("form_cadastro"):
            novo_usuario = st.text_input("Novo Usuário")
            nova_senha = st.text_input("Nova Senha", type="password")
            api_key_input = st.text_input("Sua GEMINI_API_KEY (Opcional)", type="password")
            btn_cadastrar = st.form_submit_button("Cadastrar")

            if btn_cadastrar:
                if novo_usuario and nova_senha:
                    sucesso, msg = cadastrar_usuario(novo_usuario, nova_senha, api_key_input)
                    if sucesso:
                        st.success(msg)
                    else:
                        st.error(msg)
                else:
                    st.warning("Preencha usuário e senha!")

    st.stop()


# ---------------------------------------------------------
# FUNÇÕES AUXILIARES DE TRATAMENTO DE TEXTO
# ---------------------------------------------------------
def extrair_valores_da_resposta(texto):
    cal, prot, carb, gord = 0.0, 0.0, 0.0, 0.0
    m_cal = re.search(r'Calorias:\s*([\d\.,]+)', texto, re.IGNORECASE)
    m_prot = re.search(r'Prote\u00ednas:\s*([\d\.,]+)', texto, re.IGNORECASE)
    m_carb = re.search(r'Carboidratos:\s*([\d\.,]+)', texto, re.IGNORECASE)
    m_gord = re.search(r'Gorduras:\s*([\d\.,]+)', texto, re.IGNORECASE)

    if m_cal: cal = float(m_cal.group(1).replace(',', '.'))
    if m_prot: prot = float(m_prot.group(1).replace(',', '.'))
    if m_carb: carb = float(m_carb.group(1).replace(',', '.'))
    if m_gord: gord = float(m_gord.group(1).replace(',', '.'))

    return cal, prot, carb, gord


def extrair_primeiro_nome(texto_completo):
    """
    Se o texto contiver vírgula, separa em múltiplos itens e extrai
    o primeiro nome de cada um, retornando-os separados por quebras de linha (\n).
    """
    if not texto_completo:
        return ""

    ignorar = {"g", "gr", "gramas", "kg", "ml", "de", "do", "da", "dos", "das", "em", "para", "com", "e"}

    # Se houver vírgula, divide a string pelos itens separados por vírgula
    itens = texto_completo.split(",") if "," in texto_completo else [texto_completo]
    nomes_extraidos = []

    for item in itens:
        texto_limpo = re.sub(r'[^\w\s]', ' ', str(item))
        palavras = texto_limpo.split()

        nome_item = ""
        for palavra in palavras:
            if not palavra.isdigit() and palavra.lower() not in ignorar:
                palavra_limpa = re.sub(r'^\d+g?$', '', palavra, flags=re.IGNORECASE)
                if palavra_limpa:
                    nome_item = palavra_limpa.capitalize()
                    break

        if nome_item:
            nomes_extraidos.append(nome_item)
        elif item.strip():
            nomes_extraidos.append(item.strip().split()[0].capitalize())

    return "\n".join(nomes_extraidos)


# ---------------------------------------------------------
# BARRA LATERAL (USUÁRIO LOGADO + API KEY + LOGOUT)
# ---------------------------------------------------------
st.sidebar.title(f"👤 {st.session_state.usuario_logado}")

api_key = st.sidebar.text_input(
    "GEMINI_API_KEY",
    value=st.session_state.get("api_key", ""),
    type="password",
    help="Sua chave de API fica salva no seu perfil"
)

if api_key != st.session_state.get("api_key"):
    st.session_state.api_key = api_key
    atualizar_api_key_bd(st.session_state.usuario_logado, api_key)
    cookie_manager.set("nutri_api", api_key, key="update_a")
    st.sidebar.success("API Key atualizada!")

if st.sidebar.button("🚪 Sair (Logout)"):
    st.session_state.autenticado = False
    cookie_manager.delete("nutri_user")
    cookie_manager.delete("nutri_pass")
    cookie_manager.delete("nutri_api")
    st.rerun()

# ---------------------------------------------------------
# NAVEGAÇÃO PRINCIPAL DO APP
# ---------------------------------------------------------
st.title("🥗 Assistente Nutricional Inteligente")
aba_chat, aba_cadastro, aba_historico, aba_momento = st.tabs([
    "💬 Chat de Alimentos",
    "➕ Cadastrar Refeição",
    "📋 Histórico do Dia",
    "📌 Momento"
])

PROMPT_SISTEMA_BASE = """
Você é um assistente especializado em nutrição esportiva e cálculo de macronutrientes.
O usuário enviará perguntas sobre alimentos, receitas ou fotos/imagens de refeições/rótulos.

Regras de resposta:
1. Sempre responda em português claro e direto.
2. Quando o usuário mencionar alimentos e pesos (ou enviar uma foto de comida/rótulo), entregue SEMPRE uma tabela formatada em Markdown:
   | Alimento | Quantidade (g) | Calorias (kcal) | Proteínas (g) | Carboidratos (g) | Gorduras (g) |
3. No final da resposta, inclua o TOTAL somado neste formato exato:
   TOTAL:
   - Calorias: X kcal
   - Proteínas: Y g
   - Carboidratos: Z g
   - Gorduras: W g
"""

# ABA 1: CHAT
with aba_chat:
    st.subheader("Pergunte sobre alimentos, receitas ou envie uma foto do seu prato")
    st.caption("Exemplo: 'Quantas proteínas têm 150g de peito de frango?' ou envie a foto de um prato/rótulo.")

    if "mensagens_chat" not in st.session_state:
        st.session_state.mensagens_chat = [
            {"role": "assistant",
             "content": "Olá! Pode me mandar o peso em gramas dos alimentos ou uma foto do seu prato que te entrego a tabela nutricional completa."}
        ]

    for msg in st.session_state.mensagens_chat:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if "imagem" in msg:
                st.image(msg["imagem"], width=250)

    # --- ÁREA DE ENVIO DE FOTO / CÂMARA ---
    with st.expander("📷 Anexar Foto de Prato / Rótulo Nutricional", expanded=False):
        opcao_midia = st.radio("Escolha a origem da foto:", ["📁 Carregar Arquivo (Upload)", "📸 Tirar Foto (Câmera)"],
                               horizontal=True)

        imagem_capturada = None
        if opcao_midia == "📁 Carregar Arquivo (Upload)":
            imagem_capturada = st.file_uploader("Selecione uma imagem...", type=["png", "jpg", "jpeg"],
                                                key="upload_chat")
        else:
            imagem_capturada = st.camera_input("Tire uma foto do seu prato ou rótulo", key="camera_chat")

        if imagem_capturada:
            st.image(imagem_capturada, caption="Imagem Carregada", width=200)
            legenda_foto = st.text_input("Acompanhamento / Pergunta sobre a foto (opcional):",
                                         "Analise este prato/rótulo e me dê a tabela nutricional estimada com os totais.")

            if st.button("📤 Enviar Imagem para a IA", type="primary"):
                if not api_key:
                    st.error("Por favor, insira sua GEMINI_API_KEY na barra lateral.")
                else:
                    img_pil = Image.open(imagem_capturada)

                    st.session_state.mensagens_chat.append({
                        "role": "user",
                        "content": legenda_foto,
                        "imagem": img_pil
                    })

                    client = genai.Client(api_key=api_key)
                    prompt_completo = f"{PROMPT_SISTEMA_BASE}\n\nPergunta do usuário sobre a imagem: {legenda_foto}"

                    with st.spinner("Analisando imagem com a IA..."):
                        try:
                            response = client.models.generate_content(
                                model="gemini-1.5-flash",
                                contents=[prompt_completo, img_pil]
                            )
                            resposta_ia = response.text

                            st.session_state["ultima_pergunta"] = f"[Foto] {legenda_foto}"
                            st.session_state["ultima_resposta"] = resposta_ia
                            st.session_state.mensagens_chat.append({"role": "assistant", "content": resposta_ia})
                            st.rerun()
                        except Exception as e:
                            st.error(f"Erro ao processar imagem: {e}")

    # --- CHAT DE TEXTO ---
    if prompt_usuario := st.chat_input("Digite sua dúvida ou os alimentos em gramas..."):
        if not api_key:
            st.error("Por favor, insira sua GEMINI_API_KEY na barra lateral para conversar com a IA.")
        else:
            st.session_state.mensagens_chat.append({"role": "user", "content": prompt_usuario})
            with st.chat_message("user"):
                st.markdown(prompt_usuario)

            client = genai.Client(api_key=api_key)
            prompt_completo = f"{PROMPT_SISTEMA_BASE}\n\nPergunta do usuário: {prompt_usuario}"

            with st.chat_message("assistant"):
                with st.spinner("Consultando dados nutricionais..."):
                    try:
                        response = client.models.generate_content(
                            model="gemini-3.6-flash",
                            contents=prompt_completo
                        )
                        resposta_ia = response.text
                        st.markdown(resposta_ia)

                        st.session_state["ultima_pergunta"] = prompt_usuario
                        st.session_state["ultima_resposta"] = resposta_ia
                        st.session_state.mensagens_chat.append({"role": "assistant", "content": resposta_ia})
                    except Exception as e:
                        st.error(f"Erro ao conectar com a IA: {e}")

    if "ultima_resposta" in st.session_state:
        st.divider()
        if st.button("💾 Adicionar resposta ao Gráfico e à aba Momento"):
            pergunta_salva = st.session_state["ultima_pergunta"]
            resposta_salva = st.session_state["ultima_resposta"]

            cal, prot, carb, gord = extrair_valores_da_resposta(resposta_salva)
            conn = sqlite3.connect('dieta.db')
            cursor = conn.cursor()
            cursor.execute('''
                           INSERT INTO refeicoes (alimento, peso_g, proteina_g, carboidrato_g, gordura_g, calorias)
                           VALUES (?, ?, ?, ?, ?, ?)
                           ''', (pergunta_salva, 100.0, prot, carb, gord, cal))
            conn.commit()
            conn.close()

            with open("respostas_cadastradas.txt", "a", encoding="utf-8") as file:
                file.write(f"PERGUNTA: {pergunta_salva}\nRESPOSTA:\n{resposta_salva}\n" + "=" * 50 + "\n\n")

            st.success("✅ Resposta adicionada ao Gráfico e salva na aba 'Momento'!")

# ABA 2: CADASTRO MANUAL
with aba_cadastro:
    st.subheader("Registrar Refeição no Banco de Dados")


    def salvar_refeicao(alimento, peso, prot, carb, gord, cal):
        conn = sqlite3.connect('dieta.db')
        cursor = conn.cursor()
        cursor.execute('''
                       INSERT INTO refeicoes (alimento, peso_g, proteina_g, carboidrato_g, gordura_g, calorias)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ''', (alimento, peso, prot, carb, gord, cal))
        conn.commit()
        conn.close()


    with st.form("nova_refeicao"):
        col1, col2 = st.columns(2)
        with col1:
            alimento = st.text_input("Alimento / Prato", "Peito de Frango Grelhado")
            peso = st.number_input("Peso (g)", value=150.0, step=5.0)
            prot = st.number_input("Proteínas (g)", value=46.0, step=1.0)
        with col2:
            carb = st.number_input("Carboidratos (g)", value=0.0, step=1.0)
            gord = st.number_input("Gorduras (g)", value=3.5, step=0.5)
            cal = st.number_input("Calorias (kcal)", value=220.0, step=10.0)

        submitted = st.form_submit_button("Salvar no Banco de Dados")
        if submitted:
            salvar_refeicao(alimento, peso, prot, carb, gord, cal)
            st.success(f"'{alimento}' registrado no seu SQLite!")

# ABA 3: HISTÓRICO
with aba_historico:
    st.subheader("📋 Refeições Registradas Hoje")
    conn = sqlite3.connect('dieta.db')
    cursor = conn.cursor()
    cursor.execute(
        "SELECT alimento, peso_g, proteina_g, carboidrato_g, gordura_g, calorias FROM refeicoes WHERE data = CURRENT_DATE")
    registros = cursor.fetchall()
    conn.close()

    if registros:
        st.table(registros)
    else:
        st.info("Nenhuma refeição registrada hoje no banco de dados.")

# ABA 4: MOMENTO
with aba_momento:
    st.subheader("📌 Análise da Refeição / Momento")
    sub_grafico, sub_historico = st.tabs(["📊 Gráfico de Distribuição", "📜 Histórico de Consultas Salvas"])

    with sub_grafico:
        conn = sqlite3.connect('dieta.db')
        cursor = conn.cursor()
        cursor.execute("""
                       SELECT COALESCE(SUM(calorias), 0),
                              COALESCE(SUM(proteina_g), 0),
                              COALESCE(SUM(carboidrato_g), 0),
                              COALESCE(SUM(gordura_g), 0)
                       FROM refeicoes
                       """)
        totais = cursor.fetchone()

        cursor.execute("SELECT alimento FROM refeicoes")
        alimentos_banco = cursor.fetchall()
        conn.close()

        total_cal, total_prot, total_carb, total_gord = float(totais[0]), float(totais[1]), float(totais[2]), float(
            totais[3])

        if "modo_manual" not in st.session_state:
            st.session_state.modo_manual = False

        # BOTÕES DE AÇÃO PERTO DO GRÁFICO (MODO MANUAL E ZERAR)
        col_btn1, col_btn2, _ = st.columns([1.2, 1.2, 2])

        with col_btn1:
            label_btn = "🔒 Usar Dados Salvos" if st.session_state.modo_manual else "➕ Adicionar Valores Manuais"
            if st.button(label_btn, use_container_width=True):
                st.session_state.modo_manual = not st.session_state.modo_manual
                st.rerun()

        with col_btn2:
            if st.button("🗑️ Zerar Gráfico e Banco", type="secondary", use_container_width=True):
                zerar_banco_refeicoes()
                st.session_state.modo_manual = False
                st.success("Gráfico e registros zerados com sucesso!")
                st.rerun()

        if st.session_state.modo_manual:
            st.caption("⚙️ **Modo de Ajuste Manual:**")
            col_g1, col_g2, col_g3, col_g4 = st.columns(4)
            v_kcal = col_g1.number_input("Calorias (kcal)", value=0.0, step=10.0, key="graf_kcal")
            v_prot = col_g2.number_input("Proteínas (g)", value=0.0, step=1.0, key="graf_prot")
            v_carb = col_g3.number_input("Carboidratos (g)", value=0.0, step=1.0, key="graf_carb")
            v_gord = col_g4.number_input("Gorduras (g)", value=0.0, step=0.5, key="graf_gord")
        else:
            st.caption("🔒 **Modo Automático:** Exibindo soma total dos registros.")
            v_kcal, v_prot, v_carb, v_gord = total_cal, total_prot, total_carb, total_gord

        if (v_kcal + v_prot + v_carb + v_gord) == 0:
            st.info("💡 **Nenhum dado no gráfico.** Adicione registros ou use os botões acima.")
        else:
            df_pizza = pd.DataFrame({
                "Nutriente": ["Calorias (kcal)", "Proteínas (g)", "Carboidratos (g)", "Gorduras (g)"],
                "Valor": [v_kcal, v_prot, v_carb, v_gord]
            })
            df_pizza_filtrado = df_pizza[df_pizza["Valor"] > 0]

            fig_pizza = px.pie(
                df_pizza_filtrado, values="Valor", names="Nutriente",
                title="Proporção Acumulada dos Nutrientes (Salvos)",
                color="Nutriente",
                color_discrete_map={
                    "Calorias (kcal)": "#EF553B", "Proteínas (g)": "#636EFA",
                    "Carboidratos (g)": "#00CC96", "Gorduras (g)": "#AB63FA"
                },
                hole=0.35
            )
            fig_pizza.update_traces(textinfo="label+percent+value")
            st.plotly_chart(fig_pizza, use_container_width=True)

        st.divider()
        st.markdown("### Resumo")
        if alimentos_banco:
            for item in alimentos_banco:
                nome_formatado = extrair_primeiro_nome(item[0])
                if nome_formatado:
                    st.markdown(nome_formatado)
        else:
            st.caption("Nenhum item adicionado.")

    with sub_historico:
        col_titulo, col_limpar = st.columns([3, 1])
        col_titulo.markdown("### 📜 Respostas e Consultas Salvas do Chat")
        if col_limpar.button("🗑️ Apagar Consultas Salvas"):
            if os.path.exists("respostas_cadastradas.txt"):
                open("respostas_cadastradas.txt", "w", encoding="utf-8").close()
                st.success("Consultas salvas apagadas!")
                st.rerun()

        if os.path.exists("respostas_cadastradas.txt"):
            with open("respostas_cadastradas.txt", "r", encoding="utf-8") as file:
                conteudo = file.read().strip()
            if conteudo:
                blocos = conteudo.split("=" * 50)
                for idx, bloco in enumerate(blocos, start=1):
                    if bloco.strip():
                        with st.expander(f"📌 Consulta Salva #{idx}", expanded=True):
                            st.markdown(bloco.strip())
            else:
                st.info("Nenhuma consulta salva no histórico.")
        else:
            st.info("Nenhuma consulta salva no histórico.")
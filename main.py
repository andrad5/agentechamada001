import streamlit as st
import pandas as pd
import requests
from datetime import datetime
from google.cloud import bigquery
from google.oauth2 import service_account
from streamlit_autorefresh import st_autorefresh

import streamlit as st

# --- 1. FUNÇÃO DE LOGIN ---
def login():
    if "autenticado" not in st.session_state:
        st.session_state.autenticado = False

    if not st.session_state.autenticado:
        st.title("🔐 Acesso - ICM Itaquá")
        senha_digitada = st.text_input("Senha do Ministério Infantil", type="password")
        
        if st.button("Entrar"):
            # Verifica a senha global que você moveu para o topo do Secrets
            if senha_digitada == st.secrets["app_password"]:
                st.session_state.autenticado = True
                st.rerun()
            else:
                st.error("Senha incorreta! 🚫")
        
        # O PULO DO GATO: Se não estiver autenticado, para o código aqui!
        st.stop() 

# --- 2. EXECUTA O LOGIN ---
login()

# --- 3. SÓ CHEGA AQUI SE PASSAR PELO LOGIN ---
st.title("⛪ Ministério Infantil - Itaqua")
# ... restante do seu código (tabs, BigQuery, etc) ...



# --- 1. CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Kids ICM Itaqua", page_icon="⛪", layout="centered")

# Aumentamos o intervalo para 60s para não sobrecarregar a API no Railway
st_autorefresh(interval=60 * 1000, key="datarefresh")

# --- 2. CONEXÃO COM BIGQUERY (VIA SECRETS.TOML) ---
def criar_cliente_bq():
    """Conecta ao BigQuery usando os secrets configurados"""
    info = st.secrets["gcp_service_account"]
    credentials = service_account.Credentials.from_service_account_info(info)
    return bigquery.Client(credentials=credentials, project=info["project_id"])

client = criar_cliente_bq()

# --- 3. FUNÇÃO DE SALVAMENTO (CARGA EM LOTE PARA FREE TIER) ---
def salvar_no_bq(tabela_id, lista_dados):
    """Envia dados usando Load Job para evitar erro 403"""
    try:
        df_temp = pd.DataFrame(lista_dados)
        job_config = bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")
        job = client.load_table_from_dataframe(df_temp, tabela_id, job_config=job_config)
        job.result() # Aguarda confirmação
        return True
    except Exception as e:
        st.error(f"Erro ao salvar no BigQuery: {e}")
        return False

# --- 4. WHATSAPP (EVOLUTION API NO RAILWAY) ---
def enviar_whatsapp(telefone, mensagem):
    """Envia mensagens via Railway com timeout estendido para evitar erros 502/499"""
    url = "https://evolution-api-production-de42.up.railway.app/message/sendText/Igreja_Itaqua"
    headers = {
        "apikey": "422442",
        "Content-Type": "application/json"
    }
    payload = {
        "number": str(telefone), 
        "text": mensagem,
        "linkPreview": False # Desativado para tornar a requisição mais leve
    }
    
    try:
        # Timeout de 30s para dar tempo da API processar na nuvem
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        
        if response.status_code in [200, 201]:
            return True
        else:
            st.warning(f"API instável (Status {response.status_code}). Verifique os logs no Railway.")
            return False
    except Exception as e:
        st.error(f"Erro de conexão com o WhatsApp: {e}")
        return False

# --- 5. INTERFACE DO USUÁRIO ---
st.title("⛪ Ministério Infantil - Itaqua")
tab_checkin, tab_operacao, tab_cadastro = st.tabs(["📝 Check-in", "🚨 Operação", "🆕 Cadastro"])

# --- ABA 1: CHECK-IN ---
with tab_checkin:
    st.header("Entrada de Alunos")
    query_cad = "SELECT ID, NOME_CRIANCA, NOME_RESPONSAVEL, TELEFONE_RESPONSAVEL FROM `agentes-icm-itaqua.principais_tabelas.historico_infantil` ORDER BY NOME_CRIANCA"
    
    try:
        df_cad = client.query(query_cad).to_dataframe()
        nome_sel = st.selectbox("Quem está chegando?", options=df_cad['NOME_CRIANCA'].tolist(), index=None)

        if nome_sel:
            dados = df_cad[df_cad['NOME_CRIANCA'] == nome_sel].iloc[0]
            if st.button("CONFIRMAR ENTRADA ✅", use_container_width=True, type="primary"):
                registro = [{
                    "ID_CRIANCA": str(dados['ID']), 
                    "NOME_CRIANCA": nome_sel,
                    "NOME_RESPONSAVEL": dados['NOME_RESPONSAVEL'],
                    "TELEFONE_RESPONSAVEL": str(dados['TELEFONE_RESPONSAVEL']),
                    "DATA_ENTRADA": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }]
                
                if salvar_no_bq("agentes-icm-itaqua.principais_tabelas.checkin", registro):
                    msg = f"Paz! *{nome_sel}* já está na salinha da ICM Itaquá. Tenha um ótimo culto! 🙏"
                    enviar_whatsapp(dados['TELEFONE_RESPONSAVEL'], msg)
                    st.success(f"Check-in de {nome_sel} realizado!")
                    st.rerun()
    except Exception as e:
        st.error(f"Erro ao carregar cadastros: {e}")

# --- ABA 2: OPERAÇÃO ---
with tab_operacao:
    st.header("Crianças em Sala")
    query_sala = """
        SELECT * FROM `agentes-icm-itaqua.principais_tabelas.checkin`
        WHERE DATA_ENTRADA != '' 
        AND DATE(SAFE.PARSE_TIMESTAMP('%Y-%m-%d %H:%M:%S', DATA_ENTRADA), "America/Sao_Paulo") = CURRENT_DATE("America/Sao_Paulo")
    """
    try:
        df_sala = client.query(query_sala).to_dataframe()
        if df_sala.empty:
            st.info("Nenhuma criança em sala no momento.")
        else:
            for idx, crianca in df_sala.iterrows():
                with st.container(border=True):
                    col1, col2 = st.columns([3, 1])
                    col1.write(f"👶 **{crianca['NOME_CRIANCA']}**")
                    if col2.button(f"🚽 Banheiro", key=f"op_{idx}"):
                        msg_banheiro = f"Paz! O(a) *{crianca['NOME_CRIANCA']}* precisa ir ao banheiro. Pode vir nos auxiliar? 🚽"
                        if enviar_whatsapp(crianca['TELEFONE_RESPONSAVEL'], msg_banheiro):
                            st.toast("Mensagem enviada!")
    except Exception as e:
        st.error(f"Erro ao carregar lista de sala: {e}")

# --- ABA 3: CADASTRO ---
with tab_cadastro:
    st.header("Novo Aluno")
    with st.form("cad_novo"):
        n = st.text_input("Nome da Criança")
        r = st.text_input("Nome do Responsável")
        t = st.text_input("WhatsApp (Ex: 5511988543533)")
        
        if st.form_submit_button("Salvar Cadastro"):
            if n and t:
                novo_id = str(int(datetime.now().timestamp()))
                novo_reg = [{
                    "ID": novo_id, 
                    "NOME_CRIANCA": n, 
                    "NOME_RESPONSAVEL": r, 
                    "TELEFONE_RESPONSAVEL": t
                }]
                if salvar_no_bq("agentes-icm-itaqua.principais_tabelas.historico_infantil", novo_reg):
                    st.success("Cadastrado com sucesso!")
                    st.cache_data.clear()
            else:
                st.warning("Preencha Nome e WhatsApp.")

import streamlit as st
import pandas as pd
import requests
from datetime import datetime
from google.cloud import bigquery
from google.oauth2 import service_account
from streamlit_autorefresh import st_autorefresh

# --- 1. CONFIGURAÇÃO DA PÁGINA (DEVE SER A PRIMEIRA LINHA EXECUTÁVEL) ---
st.set_page_config(page_title="Kids ICM Itaqua", page_icon="⛪", layout="centered")

# --- 2. FUNÇÃO DE LOGIN (SEGURANÇA DO APP) ---
def login():
    """Cria uma barreira de acesso antes de carregar o restante do app"""
    if "autenticado" not in st.session_state:
        st.session_state.autenticado = False

    if not st.session_state.autenticado:
        st.title("🔐 Acesso - ICM Itaquá")
        # Campo de senha lê a chave 'app_password' dos Secrets do Streamlit
        senha_digitada = st.text_input("Senha do Ministério Infantil", type="password")
        
        if st.button("Entrar", use_container_width=True):
            if senha_digitada == st.secrets["app_password"]:
                st.session_state.autenticado = True
                st.rerun()
            else:
                st.error("Senha incorreta! 🚫")
        
        # Interrompe o script para não mostrar os dados abaixo
        st.stop() 

# Executa o login
login()

# --- 3. CONFIGURAÇÕES GERAIS E CONEXÕES (SÓ RODA SE LOGADO) ---
# Autorefresh de 60s para manter a lista de sala atualizada
st_autorefresh(interval=60 * 1000, key="datarefresh")

def criar_cliente_bq():
    """Conecta ao BigQuery usando os secrets configurados no painel do Streamlit"""
    info = st.secrets["gcp_service_account"]
    credentials = service_account.Credentials.from_service_account_info(info)
    return bigquery.Client(credentials=credentials, project=info["project_id"])

client = criar_cliente_bq()

def salvar_no_bq(tabela_id, lista_dados):
    """Salva dados no BigQuery usando Load Job para evitar limites do Free Tier"""
    try:
        df_temp = pd.DataFrame(lista_dados)
        job_config = bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")
        job = client.load_table_from_dataframe(df_temp, tabela_id, job_config=job_config)
        job.result() 
        return True
    except Exception as e:
        st.error(f"Erro ao salvar no BigQuery: {e}")
        return False

def enviar_whatsapp(telefone, mensagem):
    """Envia mensagens via Evolution API no Railway com timeout estendido"""
    url = "https://evolution-api-production-de42.up.railway.app/message/sendText/Igreja_Itaqua"
    headers = {
        "apikey": "422442",
        "Content-Type": "application/json"
    }
    payload = {
        "number": str(telefone), 
        "text": mensagem,
        "linkPreview": False 
    }
    
    try:
        # Timeout aumentado para 40s para lidar com a instabilidade da API
        response = requests.post(url, json=payload, headers=headers, timeout=40)
        if response.status_code in [200, 201]:
            return True
        else:
            st.warning(f"API instável (Status {response.status_code}).")
            return False
    except Exception as e:
        st.error(f"Erro de conexão com o WhatsApp: {e}")
        return False

# --- 4. INTERFACE DO USUÁRIO ---
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
    # Filtra apenas o check-in do dia atual (Fuso SP)
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
                
               c1, c2, c3 = st.columns(3)
                
                with c1:
                    if st.button("🚽 Banheiro", key=f"ban_{idx}"):
                        txt = f"Paz do Senhor {crianca['nome_responsavel']}, o(a) {crianca['nome_crianca']} precisa ir ao banheiro. Pode nos auxiliar?"
                        enviar_whatsapp_api(crianca['telefone_responsavel'], txt)
                        st.toast(f"Aviso enviado para {crianca['nome_responsavel']}!")

                with c2:
                    if st.button("😢 Choro", key=f"cho_{idx}"):
                        txt = f"Paz do Senhor {crianca['nome_responsavel']}, o(a) {crianca['nome_crianca']} está sentindo sua falta. Poderia vir dar um abraço nele(a)?"
                        enviar_whatsapp_api(crianca['telefone_responsavel'], txt)
                        st.toast(f"Aviso enviado!")

                with c3:
                    if st.button("🚨 Chamar", key=f"urg_{idx}"):
                        txt = f"Paz do Senhor {crianca['nome_responsavel']}, solicitamos sua presença na salinha das crianças para auxiliar o(a) {crianca['nome_crianca']}."
                        enviar_whatsapp_api(crianca['telefone_responsavel'], txt)
                        st.toast(f"Chamado urgente enviado!")
                
               # with st.container(border=True):
               #     col1, col2 = st.columns([3, 1])
               #     col1.write(f"👶 **{crianca['NOME_CRIANCA']}**")
               #     if col2.button(f"🚽 Banheiro", key=f"op_{idx}"):
               #         msg_banheiro = f"Paz! O(a) *{crianca['NOME_CRIANCA']}* precisa ir ao banheiro. Pode vir nos auxiliar? 🚽"
               #         if enviar_whatsapp(crianca['TELEFONE_RESPONSAVEL'], msg_banheiro):
               #             st.toast("Mensagem enviada!")
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

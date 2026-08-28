import os
import streamlit as st
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client, Client
import urllib.parse

# Configuración inicial de la página
st.set_page_config(
    page_title="Control Financiero Personal",
    page_icon="💳",
    layout="wide",
    initial_sidebar_state="expanded"
)

load_dotenv()

# Conexión a Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL") or st.secrets.get("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY") or st.secrets.get("SUPABASE_KEY", "")

@st.cache_resource
def get_supabase_client() -> Client:
    return create_client(SUPABASE_URL.strip(), SUPABASE_KEY.strip())

supabase = get_supabase_client()

# Consultas a la base de datos
def load_contacts():
    try:
        res = supabase.table("contacts").select("*").order("name").execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame(columns=["id", "name"])
    except Exception:
        return pd.DataFrame(columns=["id", "name"])

def load_transactions():
    try:
        res = supabase.table("transactions").select("*, contacts(name, phone)").order("transaction_date", desc=True).execute()
        if not res.data:
            return pd.DataFrame()
        
        rows = []
        for row in res.data:
            contact_info = row.get("contacts") or {}
            rows.append({
                "id": row.get("id"),
                "fecha": row.get("transaction_date"),
                "mes": row.get("billing_month"),
                "tipo": row.get("type"),
                "descripcion": row.get("description"),
                "monto": float(row.get("amount", 0)),
                "cuotas": row.get("installments", 1),
                "estado": row.get("status", "PENDIENTE"),
                "contacto_id": row.get("contact_id"),
                "persona": contact_info.get("name", "Personal"),
                "telefono": contact_info.get("phone", "")
            })
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame()

# Barra lateral
st.sidebar.title("⚙️ Filtros y Opciones")

df_contacts = load_contacts()
df_tx = load_transactions()

# Selector de Mes
mes_actual = datetime.now().strftime("%Y-%m")
meses_disponibles = sorted(list(df_tx["mes"].dropna().unique()), reverse=True) if not df_tx.empty and "mes" in df_tx else [mes_actual]
if mes_actual not in meses_disponibles:
    meses_disponibles.insert(0, mes_actual)

mes_seleccionado = st.sidebar.selectbox("Seleccionar Mes Contable", meses_disponibles, index=0)

# Filtrar por mes
if not df_tx.empty:
    df_mes = df_tx[df_tx["mes"] == mes_seleccionado]
else:
    df_mes = pd.DataFrame()

# Pestañas
tab_dashboard, tab_cobranzas, tab_contactos, tab_historial = st.tabs([
    "📊 Resumen del Mes", 
    "💳 Préstamos y Cobros", 
    "👥 Gestión de Personas", 
    "📝 Todas las Transacciones"
])

# 1. DASHBOARD
with tab_dashboard:
    st.header(f"Resumen Financiero — {mes_seleccionado}")
    
    if not df_mes.empty:
        gasto_propio = df_mes[df_mes["tipo"] == "GASTO_PROPIO"]["monto"].sum()
        prestamo_pendiente = df_mes[(df_mes["tipo"] == "PRESTAMO_TERCERO") & (df_mes["estado"] == "PENDIENTE")]["monto"].sum()
        prestamo_cobrado = df_mes[(df_mes["tipo"] == "PRESTAMO_TERCERO") & (df_mes["estado"] == "COBRADO")]["monto"].sum()
    else:
        gasto_propio, prestamo_pendiente, prestamo_cobrado = 0.0, 0.0, 0.0

    col1, col2, col3 = st.columns(3)
    col1.metric("🛒 Gasto Propio del Mes", f"S/ {gasto_propio:,.2f}")
    col2.metric("⏳ Por Cobrar a Terceros", f"S/ {prestamo_pendiente:,.2f}")
    col3.metric("✅ Cobrado / Recuperado", f"S/ {prestamo_cobrado:,.2f}")

    st.divider()
    st.subheader("Movimientos del Mes")
    if not df_mes.empty:
        cols_mostrar = [c for c in ["fecha", "tipo", "descripcion", "monto", "persona", "estado"] if c in df_mes.columns]
        st.dataframe(df_mes[cols_mostrar], use_container_width=True, hide_index=True)
    else:
        st.info("No hay transacciones registradas para este mes.")

# 2. PRÉSTAMOS Y COBROS
with tab_cobranzas:
    st.header("Control de Deudas por Persona")
    
    if not df_tx.empty:
        deudas_pendientes = df_tx[(df_tx["tipo"] == "PRESTAMO_TERCERO") & (df_tx["estado"] == "PENDIENTE")]
    else:
        deudas_pendientes = pd.DataFrame()

    if deudas_pendientes.empty:
        st.success("🎉 No tienes préstamos pendientes de cobro.")
    else:
        personas_deudoras = [p for p in deudas_pendientes["persona"].unique() if p != "Personal"]
        
        for persona in personas_deudoras:
            tx_persona = deudas_pendientes[deudas_pendientes["persona"] == persona]
            total_deuda = tx_persona["monto"].sum()
            telefono = tx_persona["telefono"].iloc[0] if "telefono" in tx_persona.columns and not tx_persona.empty else ""
            
            with st.expander(f"👤 {persona} — Total Pendiente: S/ {total_deuda:,.2f}", expanded=True):
                detalle_items = "\n".join([f"• {r['descripcion']}: S/ {r['monto']:,.2f}" for _, r in tx_persona.iterrows()])
                mensaje_wa = f"Hola {persona}! Te comparto el detalle de tus consumos pendientes:\n\n{detalle_items}\n\n*Total a pagar:* S/ {total_deuda:,.2f}"
                wa_url = f"https://wa.me/{telefono}?text={urllib.parse.quote(mensaje_wa)}" if telefono else f"https://wa.me/?text={urllib.parse.quote(mensaje_wa)}"
                
                st.link_button("📲 Enviar Cobro por WhatsApp", wa_url)
                st.write("**Detalle:**")
                for _, r in tx_persona.iterrows():
                    c1, c2, c3 = st.columns([3, 1, 1])
                    c1.write(f"📅 {r['fecha']} | {r['descripcion']}")
                    c2.write(f"**S/ {r['monto']:,.2f}**")
                    if c3.button("Marcar Cobrado", key=f"cobrar_{r['id']}"):
                        supabase.table("transactions").update({"status": "COBRADO"}).eq("id", r["id"]).execute()
                        st.toast("¡Registro actualizado!")
                        st.rerun()

# 3. GESTIÓN DE PERSONAS
with tab_contactos:
    st.header("Directorio de Contactos")
    
    col_form, col_list = st.columns([1, 2])
    
    with col_form:
        st.subheader("➕ Agregar Persona")
        with st.form("form_nuevo_contacto", clear_on_submit=True):
            nuevo_nombre = st.text_input("Nombre / Apodo *")
            nuevo_telefono = st.text_input("Teléfono (opcional)")
            submitted = st.form_submit_button("Guardar")
            
            if submitted:
                if nuevo_nombre.strip():
                    payload = {"name": nuevo_nombre.strip()}
                    if nuevo_telefono.strip():
                        payload["phone"] = nuevo_telefono.strip()
                    supabase.table("contacts").insert(payload).execute()
                    st.success(f"Persona '{nuevo_nombre}' registrada.")
                    st.rerun()
                else:
                    st.error("El nombre es obligatorio.")
                    
    with col_list:
        st.subheader("Personas Registradas")
        if not df_contacts.empty:
            cols_disponibles = [c for c in ["name", "phone", "id"] if c in df_contacts.columns]
            st.dataframe(df_contacts[cols_disponibles], use_container_width=True, hide_index=True)
        else:
            st.info("No hay contactos en la lista.")

# 4. HISTORIAL COMPLETO
with tab_historial:
    st.header("Historial Completo de Transacciones")
    if not df_tx.empty:
        st.dataframe(df_tx, use_container_width=True, hide_index=True)
    else:
        st.info("No hay transacciones registradas.")

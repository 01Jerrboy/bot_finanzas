import os
import streamlit as st
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client, Client
import urllib.parse

# 1. Configuración de página
st.set_page_config(
    page_title="Control Financiero Personal",
    page_icon="💳",
    layout="wide",
    initial_sidebar_state="expanded"
)

load_dotenv()

# 2. Conexión a Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL") or st.secrets.get("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY") or st.secrets.get("SUPABASE_KEY", "")

@st.cache_resource
def get_supabase_client() -> Client:
    return create_client(SUPABASE_URL.strip(), SUPABASE_KEY.strip())

supabase = get_supabase_client()

# 3. Consultas a la base de datos
def load_contacts():
    try:
        res = supabase.table("contacts").select("*").order("name").execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame(columns=["id", "name", "phone"])
    except Exception:
        return pd.DataFrame(columns=["id", "name", "phone"])

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
                "cuotas": int(row.get("installments", 1)),
                "estado": row.get("status", "PENDIENTE"),
                "contacto_id": row.get("contact_id"),
                "persona": contact_info.get("name", "Personal"),
                "telefono": contact_info.get("phone", "")
            })
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame()

# 4. Filtros en la barra lateral
st.sidebar.title("⚙️ Filtros y Opciones")

df_contacts = load_contacts()
df_tx = load_transactions()

mes_actual = datetime.now().strftime("%Y-%m")
meses_disponibles = sorted(list(df_tx["mes"].dropna().unique()), reverse=True) if not df_tx.empty and "mes" in df_tx else [mes_actual]
if mes_actual not in meses_disponibles:
    meses_disponibles.insert(0, mes_actual)

mes_seleccionado = st.sidebar.selectbox("Seleccionar Mes Contable", meses_disponibles, index=0)

if not df_tx.empty:
    df_mes = df_tx[df_tx["mes"] == mes_seleccionado]
else:
    df_mes = pd.DataFrame()

# 5. Pestañas de la aplicación
tab_dashboard, tab_cobranzas, tab_contactos, tab_transacciones = st.tabs([
    "📊 Resumen del Mes", 
    "💳 Préstamos y Cobros", 
    "👥 Gestión de Personas (CRUD)", 
    "📝 Gestión de Transacciones (CRUD)"
])

# ==========================================
# 📊 PESTAÑA 1: RESUMEN DEL MES
# ==========================================
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

# ==========================================
# 💳 PESTAÑA 2: PRÉSTAMOS Y COBROS
# ==========================================
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
                st.write("**Detalle de consumos:**")
                for _, r in tx_persona.iterrows():
                    c1, c2, c3 = st.columns([3, 1, 1])
                    c1.write(f"📅 {r['fecha']} | {r['descripcion']}")
                    c2.write(f"**S/ {r['monto']:,.2f}**")
                    if c3.button("Marcar Cobrado", key=f"cobrar_{r['id']}"):
                        supabase.table("transactions").update({"status": "COBRADO"}).eq("id", r["id"]).execute()
                        st.toast("¡Registro actualizado!")
                        st.rerun()

# ==========================================
# 👥 PESTAÑA 3: GESTIÓN DE PERSONAS (CRUD)
# ==========================================
with tab_contactos:
    st.header("Directorio de Contactos")
    
    col_form, col_list = st.columns([1, 2])
    
    # CREATE: Formulario para agregar persona
    with col_form:
        st.subheader("➕ Nueva Persona")
        with st.form("form_nuevo_contacto", clear_on_submit=True):
            nuevo_nombre = st.text_input("Nombre / Apodo *")
            nuevo_telefono = st.text_input("Teléfono (Ej: 51987654321)")
            submitted = st.form_submit_button("Guardar Persona")
            
            if submitted:
                if nuevo_nombre.strip():
                    try:
                        payload = {"name": nuevo_nombre.strip()}
                        if nuevo_telefono.strip():
                            payload["phone"] = nuevo_telefono.strip()
                        supabase.table("contacts").insert(payload).execute()
                        st.toast(f"Persona '{nuevo_nombre}' creada con éxito.")
                        st.rerun()
                    except Exception as err:
                        st.error(f"Error al guardar: {err}")
                else:
                    st.warning("El nombre es obligatorio.")
                    
    # READ, UPDATE, DELETE: Lista editable de personas
    with col_list:
        st.subheader("Directorio Registrado")
        if not df_contacts.empty:
            for _, c in df_contacts.iterrows():
                tel_val = c.get("phone") if pd.notna(c.get("phone")) and c.get("phone") else ""
                tel_display = f"📞 {tel_val}" if tel_val else "Sin teléfono"
                
                with st.expander(f"👤 {c['name']} ({tel_display})"):
                    # Formulario de edición (UPDATE)
                    with st.form(f"edit_contact_{c['id']}"):
                        edit_name = st.text_input("Nombre", value=c["name"])
                        edit_phone = st.text_input("Teléfono", value=tel_val)
                        
                        btn_update = st.form_submit_button("💾 Guardar Cambios")
                        if btn_update:
                            try:
                                supabase.table("contacts").update({
                                    "name": edit_name.strip(),
                                    "phone": edit_phone.strip() if edit_phone.strip() else None
                                }).eq("id", c["id"]).execute()
                                st.toast("Contacto actualizado.")
                                st.rerun()
                            except Exception as err:
                                st.error(f"Error al actualizar: {err}")
                    
                    # Botón de eliminación (DELETE)
                    if st.button("🗑️ Eliminar Contacto", key=f"del_c_{c['id']}", type="secondary"):
                        try:
                            # Desvincular transacciones previas
                            supabase.table("transactions").update({"contact_id": None}).eq("contact_id", c["id"]).execute()
                            # Eliminar contacto
                            supabase.table("contacts").delete().eq("id", c["id"]).execute()
                            st.toast(f"'{c['name']}' eliminado correctamente.")
                            st.rerun()
                        except Exception as err:
                            st.error(f"Error al eliminar: {err}")
        else:
            st.info("No hay contactos en la lista.")

# ==========================================
# 📝 PESTAÑA 4: GESTIÓN DE TRANSACCIONES (CRUD)
# ==========================================
with tab_transacciones:
    st.header("Gestión de Transacciones")
    
    # CREATE: Nueva transacción manual
    with st.expander("➕ Registrar Nueva Transacción Manual"):
        with st.form("form_nueva_tx", clear_on_submit=True):
            f_col1, f_col2, f_col3 = st.columns(3)
            nueva_fecha = f_col1.date_input("Fecha", value=datetime.today())
            nueva_desc = f_col2.text_input("Descripción * (Ej: Almuerzo chifa)")
            nuevo_monto = f_col3.number_input("Monto (S/) *", min_value=0.1, step=0.5)
            
            f_col4, f_col5, f_col6 = st.columns(3)
            nuevo_tipo = f_col4.selectbox("Tipo", ["GASTO_PROPIO", "PRESTAMO_TERCERO"])
            
            # Selector de contacto
            contact_options = {"(Ninguno / Personal)": None}
            if not df_contacts.empty:
                for _, row_c in df_contacts.iterrows():
                    contact_options[row_c["name"]] = row_c["id"]
            
            contacto_seleccionado = f_col5.selectbox("Asignar a Persona", list(contact_options.keys()))
            nuevo_estado = f_col6.selectbox("Estado", ["PENDIENTE", "COBRADO"])
            
            nuevo_mes = f_col4.text_input("Mes Contable (YYYY-MM)", value=datetime.today().strftime("%Y-%m"))
            nuevas_cuotas = f_col5.number_input("Cuotas", min_value=1, value=1)
            
            submitted_tx = st.form_submit_button("Registrar Transacción")
            if submitted_tx:
                if nueva_desc.strip() and nuevo_monto > 0:
                    try:
                        tx_payload = {
                            "transaction_date": str(nueva_fecha),
                            "billing_month": nuevo_mes.strip(),
                            "type": nuevo_tipo,
                            "description": nueva_desc.strip(),
                            "amount": float(nuevo_monto),
                            "installments": int(nuevas_cuotas),
                            "status": nuevo_estado,
                            "contact_id": contact_options[contacto_seleccionado]
                        }
                        supabase.table("transactions").insert(tx_payload).execute()
                        st.toast("Transacción guardada.")
                        st.rerun()
                    except Exception as err:
                        st.error(f"Error al registrar: {err}")
                else:
                    st.warning("Completa la descripción y el monto.")
    
    st.divider()
    
    # READ, UPDATE, DELETE: Lista de transacciones
    st.subheader("Historial y Edición de Registros")
    if not df_tx.empty:
        for _, tx in df_tx.iterrows():
            with st.expander(f"📅 {tx['fecha']} | {tx['descripcion']} — S/ {tx['monto']:,.2f} ({tx['persona']} - {tx['estado']})"):
                with st.form(f"edit_tx_{tx['id']}"):
                    e1, e2, e3 = st.columns(3)
                    e_desc = e1.text_input("Descripción", value=tx["descripcion"])
                    e_monto = e2.number_input("Monto (S/)", value=float(tx["monto"]), step=0.5)
                    e_tipo = e3.selectbox("Tipo", ["GASTO_PROPIO", "PRESTAMO_TERCERO"], index=0 if tx["tipo"] == "GASTO_PROPIO" else 1)
                    
                    e4, e5, e6 = st.columns(3)
                    e_mes = e4.text_input("Mes Contable", value=tx["mes"])
                    e_estado = e5.selectbox("Estado", ["PENDIENTE", "COBRADO"], index=0 if tx["estado"] == "PENDIENTE" else 1)
                    
                    # Persona asignada
                    current_idx = 0
                    if tx["persona"] in list(contact_options.keys()):
                        current_idx = list(contact_options.keys()).index(tx["persona"])
                    e_persona = e6.selectbox("Persona", list(contact_options.keys()), index=current_idx)
                    
                    btn_save_tx = st.form_submit_button("💾 Guardar Cambios en Transacción")
                    if btn_save_tx:
                        try:
                            supabase.table("transactions").update({
                                "description": e_desc.strip(),
                                "amount": float(e_monto),
                                "type": e_tipo,
                                "billing_month": e_mes.strip(),
                                "status": e_estado,
                                "contact_id": contact_options[e_persona]
                            }).eq("id", tx["id"]).execute()
                            st.toast("Transacción actualizada.")
                            st.rerun()
                        except Exception as err:
                            st.error(f"Error al actualizar: {err}")
                
                # DELETE Transacción
                if st.button("🗑️ Eliminar Transacción", key=f"del_tx_{tx['id']}", type="secondary"):
                    try:
                        supabase.table("transactions").delete().eq("id", tx["id"]).execute()
                        st.toast("Transacción eliminada.")
                        st.rerun()
                    except Exception as err:
                        st.error(f"Error al eliminar: {err}")
    else:
        st.info("No hay transacciones registradas.")

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import time
from src.utils import load_status, load_crawl_history, save_crawl_history
from src.state import start_crawler, is_crawler_running

st.title("🏠 Vue d'ensemble")
st.markdown("Monitoring en temps réel pour votre crawler KidSearch")

running = is_crawler_running()
status = load_status()

col1, col2, col3, col4 = st.columns(4)

if status:
    with col1:
        st.metric(
            "Sites Crawlés",
            f"{status.get('sites_crawled', 0)} / {status.get('total_sites', 0)}",
        )
    with col2:
        st.metric("Pages Indexées", f"{status.get('pages_indexed', 0):,}")
    with col3:
        st.metric("Erreurs", status.get("errors", 0), delta_color="inverse")
    with col4:
        duration = status.get('last_crawl_duration_sec', 0)
        st.metric("Dernière Durée", f"{duration:.2f}s")

    if status.get('total_sites', 0) > 0:
        progress = status.get("sites_crawled", 0) / status["total_sites"]
        st.progress(progress, text=f"Progression: {progress * 100:.1f}%")

    active_site = status.get('active_site')
    if active_site and running:
        st.info(f"🔄 **Site en cours de crawl :** `{active_site}`")

    history = load_crawl_history()
    if len(history) > 1:
        st.subheader("📈 Évolution des Crawls")
        df_history = pd.DataFrame(history)
        df_history['timestamp'] = pd.to_datetime(df_history['timestamp'])

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_history['timestamp'],
            y=df_history['pages_indexed'],
            mode='lines+markers',
            name='Pages Indexées',
            line=dict(color='#667eea', width=3)
        ))
        fig.update_layout(
            title="Évolution du nombre de pages indexées",
            xaxis_title="Date",
            yaxis_title="Pages",
            hovermode='x unified',
            height=300
        )
        st.plotly_chart(fig, use_container_width=True)

    if "stats" in status and status["stats"]:
        st.subheader("🌍 Performance par Site")
        df = pd.DataFrame(status["stats"])
        if not df.empty:
            fig = px.bar(
                df, x="site", y="pages", color="status",
                title="Pages indexées par site",
                text="pages",
                color_discrete_map={
                    'completed': '#10b981',
                    'in_progress': '#3b82f6',
                    'error': '#f59e0b',
                    'success': '#10b981'
                }
            )
            fig.update_traces(textposition='outside')
            fig.update_layout(
                xaxis_title="Site",
                yaxis_title="Nombre de pages",
                showlegend=True,
                legend_title_text="Statut"
            )
            st.plotly_chart(fig, use_container_width=True)

            with st.expander("📋 Voir le tableau détaillé"):
                st.dataframe(df, use_container_width=True)
else:
    st.warning("⚠️ Aucun statut de crawl disponible. Lancez un crawl pour commencer !")
    if st.button("🚀 Lancer le premier crawl", type="primary"):
        start_crawler()

st.markdown("---")
if running:
    if status:
        save_crawl_history(status)

    if 'pause_refresh' not in st.session_state:
        st.session_state.pause_refresh = False

    col1, col2 = st.columns([3, 1])
    with col1:
        refresh_rate = st.slider("⏱️ Actualisation automatique (secondes)", 5, 60, 10, key="refresh_slider",
                                 disabled=st.session_state.pause_refresh)
    with col2:
        st.write("")
        st.write("")
        if st.session_state.pause_refresh:
            if st.button("▶️ Reprendre"):
                st.session_state.pause_refresh = False
                st.rerun()
        else:
            if st.button("⏸️ Pause"):
                st.session_state.pause_refresh = True
                st.rerun()

    if not st.session_state.pause_refresh:
        time.sleep(refresh_rate)
        st.rerun()
else:
    st.caption("💡 Le dashboard s'actualise automatiquement pendant les crawls.")

import streamlit as st
import yaml
import time

from src.utils import load_sites_config, save_sites_config
from src.state import is_crawler_running

st.header("⚙️ Configuration des Sites")

running = is_crawler_running()
sites_config = load_sites_config()

if sites_config is None:
    st.error("❌ Impossible de charger la configuration. Vérifiez que `config/sites.yml` existe.")
else:
    tab1, tab2 = st.tabs(["📝 Éditeur", "👁️ Aperçu"])

    with tab1:
        st.info("💡 Modifiez la configuration YAML ci-dessous. Les changements seront appliqués au prochain crawl.")

        try:
            config_text = yaml.dump(sites_config, default_flow_style=False, allow_unicode=True, sort_keys=False)
        except Exception:
            config_text = "Impossible de formater la configuration existante."

        edited_config = st.text_area(
            "Configuration sites.yml:",
            value=config_text,
            height=500,
            key="config_editor",
            disabled=running
        )

        if running:
            st.warning("L'édition est désactivée pendant qu'un crawl est en cours.")

        col1, col2, _ = st.columns([1, 1, 4])

        with col1:
            if st.button("💾 Sauvegarder", type="primary", disabled=running):
                try:
                    new_config = yaml.safe_load(edited_config)
                    if save_sites_config(new_config):
                        st.success("✅ Configuration sauvegardée avec succès !")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("❌ Erreur lors de la sauvegarde du fichier.")
                except yaml.YAMLError as e:
                    st.error(f"❌ Erreur de syntaxe YAML: {e}")

        with col2:
            if st.button("🔄 Réinitialiser", disabled=running):
                st.rerun()

    with tab2:
        if 'sites' in sites_config:
            st.subheader(f"📋 {len(sites_config['sites'])} sites configurés")

            for site in sites_config['sites']:
                with st.expander(f"🌐 {site.get('name', 'Nom non défini')}"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"**Type:** `{site.get('type')}`")
                        st.write(f"**URL de départ:** {site.get('crawl')}")
                        st.write(f"**Max pages:** {site.get('max_pages', 'Illimité')}")
                    with col2:
                        st.write(f"**Profondeur:** {site.get('depth', 'Illimitée')}")
                        st.write(f"**Délai:** {site.get('delay', 'Auto')}s")
                        if 'lang' in site:
                            st.write(f"**Langue:** `{site.get('lang')}`")

                    if site.get('exclude'):
                        st.write("**Exclusions:**")
                        st.code('\n'.join(site['exclude']), language='text')

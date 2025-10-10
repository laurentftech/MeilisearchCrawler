import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime
from urllib.parse import urlparse
import time
import json

from src.meilisearch_client import get_meili_client
from src.config import INDEX_NAME, CACHE_FILE
from src.state import is_crawler_running
from src.i18n import get_translator

# Initialiser le traducteur
if 'lang' not in st.session_state:
    st.session_state.lang = "fr"
t = get_translator(st.session_state.lang)

st.title(t("tree.title"))
st.markdown(t("tree.subtitle"))

meili_client = get_meili_client()
running = is_crawler_running()

@st.cache_data(ttl=60)
def load_cache_urls():
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            cache_data = json.load(f)
            return {url: data for url, data in cache_data.items() if url != '_meta'}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

if not meili_client:
    st.error(t("tree.error_meili_connection"))
else:
    try:
        index_ref = meili_client.index(INDEX_NAME)

        sites_list = [t("tree.all_sites")]
        with st.spinner(t("tree.loading_sites")):
            try:
                facet_result = index_ref.search("", {'facets': ['site'], 'limit': 0})
                if 'facetDistribution' in facet_result and 'site' in facet_result['facetDistribution']:
                    sites_list.extend(list(facet_result['facetDistribution']['site'].keys()))
            except Exception:
                pass

        col1, col2, col3 = st.columns(3)
        with col1:
            viz_type = st.selectbox(t("tree.viz_type"), ["TreeMap", "Sunburst", "Icicle"], help=t("tree.viz_help"))
        with col2:
            max_pages = st.slider(t("tree.max_pages"), 50, 1000, 200, 50, help=t("tree.max_pages_help"))
        with col3:
            filter_site = st.selectbox(t("tree.filter_site"), sites_list, help=t("tree.filter_site_help"))

        with st.spinner(t("tree.loading_pages").format(max_pages=max_pages)):
            params = {'limit': max_pages, 'fields': ['url', 'site', 'title', 'indexed_at', 'last_modified', 'timestamp', 'last_crawled_at', 'content_hash']}
            if filter_site != t("tree.all_sites"):
                params['filter'] = f'site = "{filter_site}"'
            documents = index_ref.get_documents(params).results

        if not documents:
            st.warning(t("tree.no_pages_found"))
        else:
            data_map = {}
            now = datetime.now()

            for doc in documents:
                doc_dict = doc if isinstance(doc, dict) else doc.__dict__
                url = doc_dict.get('url', '')
                if not url: continue

                indexed_at = doc_dict.get('indexed_at') or doc_dict.get('last_modified') or doc_dict.get('timestamp')
                last_crawled = doc_dict.get('last_crawled_at') or indexed_at

                freshness_days, freshness_category, freshness_color = (999, t("tree.unknown_date"), "#6b7280")
                if indexed_at:
                    try:
                        indexed_date = datetime.fromtimestamp(indexed_at) if isinstance(indexed_at, (int, float)) else datetime.fromisoformat(str(indexed_at).replace('Z', '+00:00'))
                        freshness_days = (now - indexed_date.replace(tzinfo=None)).days
                        if freshness_days < 1: freshness_category, freshness_color = (t("tree.indexed_today"), "#22c55e")
                        elif freshness_days < 7: freshness_category, freshness_color = (t("tree.indexed_this_week"), "#84cc16")
                        elif freshness_days < 30: freshness_category, freshness_color = (t("tree.indexed_this_month"), "#eab308")
                        elif freshness_days < 90: freshness_category, freshness_color = (t("tree.indexed_1_3_months"), "#f97316")
                        else: freshness_category, freshness_color = (t("tree.indexed_3_plus_months"), "#ef4444")
                    except Exception as e: freshness_category = t("tree.date_error").format(e=str(e)[:20])

                last_crawl_days, last_crawl_text = (999, t("tree.never_crawled"))
                if last_crawled:
                    try:
                        crawled_date = datetime.fromtimestamp(last_crawled) if isinstance(last_crawled, (int, float)) else datetime.fromisoformat(str(last_crawled).replace('Z', '+00:00'))
                        last_crawl_days = (now - crawled_date.replace(tzinfo=None)).days
                        if last_crawl_days < 1: last_crawl_text = t("tree.crawled_today")
                        else: last_crawl_text = t("tree.crawled_days_ago").format(days=last_crawl_days)
                    except Exception: pass

                parsed = urlparse(url)
                path_parts = [p for p in parsed.path.split('/') if p]
                data_map[url] = {
                    'site': doc_dict.get('site', 'Unknown'), 'path_parts': path_parts,
                    'page': path_parts[-1][:40] if path_parts else t("tree.homepage"),
                    'url': url, 'title': doc_dict.get('title', t("tree.no_title"))[:100],
                    'freshness_days': freshness_days, 'freshness_category': freshness_category, 'freshness_color': freshness_color,
                    'last_crawl_days': last_crawl_days, 'last_crawl_text': last_crawl_text, 'status': 'indexed'
                }

            cached_data = load_cache_urls()
            for url, cache_info in cached_data.items():
                if url not in data_map:
                    if filter_site != t("tree.all_sites") and filter_site.lower() not in url.lower(): continue
                    parsed = urlparse(url)
                    path_parts = [p for p in parsed.path.split('/') if p]
                    last_crawl_timestamp = cache_info.get('last_crawl', 0) if isinstance(cache_info, dict) else 0
                    crawl_age_days, crawl_text = (999, t("tree.unknown_date"))
                    if last_crawl_timestamp:
                        crawl_date = datetime.fromtimestamp(last_crawl_timestamp)
                        crawl_age_days = (now - crawl_date).days
                        if crawl_age_days < 1: crawl_text = t("tree.crawled_today")
                        else: crawl_text = t("tree.crawled_days_ago").format(days=crawl_age_days)
                    data_map[url] = {
                        'site': parsed.netloc, 'path_parts': path_parts,
                        'page': path_parts[-1][:40] if path_parts else t("tree.homepage"), 'url': url,
                        'title': t("tree.pending_indexing"), 'freshness_days': 9999, 'freshness_category': t("tree.pending_status"),
                        'freshness_color': "#4b5563", 'last_crawl_days': crawl_age_days, 'last_crawl_text': crawl_text, 'status': 'pending'
                    }

            df = pd.DataFrame(list(data_map.values()))

            if df.empty:
                st.warning(t("tree.error_processing"))
            else:
                st.markdown("---")
                col1, col2, col3, col4, col5 = st.columns(5)
                col1.metric(t("tree.analyzed_pages"), len(df))
                col2.metric(t("tree.sites"), df['site'].nunique())
                avg_freshness = df[df['freshness_days'] < 999]['freshness_days'].mean()
                col3.metric(t("tree.index_age"), f"{avg_freshness:.0f}j" if pd.notna(avg_freshness) else t("tree.not_available"))
                col4.metric(t("tree.indexed_less_than_7_days"), len(df[df['freshness_days'] < 7]))
                pending_count = len(df[df['status'] == 'pending'])
                if pending_count > 0: col5.metric(t("tree.pending_pages"), pending_count)
                else: col5.metric(t("tree.crawled_less_than_7_days"), len(df[df['last_crawl_days'] < 7]))

                st.markdown("---")
                col1, col2, col3 = st.columns(3)
                if stale_pages := len(df[df['last_crawl_days'] > 30]): col1.metric(t("tree.to_recrawl"), stale_pages, help=t("tree.to_recrawl_help"))
                if old_indexed := len(df[df['freshness_days'] > 90]): col2.metric(t("tree.old_indexing"), old_indexed, help=t("tree.old_indexing_help"))
                if pending_count > 0: col3.metric(t("tree.queue"), pending_count, help=t("tree.queue_help"))

                labels, parents, values, colors, hover_texts, ids = [t("tree.all_pages_root")], [""], [len(df)], [30], [t("tree.root_hover").format(total=len(df))], ["root"]
                node_map = {"": "root"}
                id_counter = 0

                for site_name in df['site'].unique():
                    id_counter += 1; site_id = f"site_{id_counter}"
                    site_data = df[df['site'] == site_name]
                    labels.append(site_name); parents.append("root"); values.append(len(site_data)); colors.append(30)
                    hover_texts.append(t("tree.site_hover").format(site=site_name, count=len(site_data))); ids.append(site_id)
                    node_map[site_name] = site_id

                    for _, row in site_data.iterrows():
                        current_parent_id, current_path = site_id, site_name
                        for part in row['path_parts'][:-1]:
                            current_path += f"/{part}"
                            if current_path not in node_map:
                                id_counter += 1; folder_id = f"folder_{id_counter}"
                                labels.append(part[:30]); parents.append(current_parent_id); values.append(1); colors.append(30)
                                hover_texts.append(t("tree.folder_hover").format(folder=part)); ids.append(folder_id)
                                node_map[current_path] = folder_id
                                current_parent_id = folder_id
                            else:
                                current_parent_id = node_map[current_path]
                                values[ids.index(current_parent_id)] += 1
                        
                        id_counter += 1; page_id = f"page_{id_counter}"
                        labels.append(row['page']); parents.append(current_parent_id); values.append(1); ids.append(page_id)
                        if row['status'] == 'pending':
                            colors.append(181)
                            hover_texts.append(t("tree.pending_hover").format(url=row['url'][:60], crawled_text=row['last_crawl_text']))
                        else:
                            colors.append(row['freshness_days'])
                            hover_texts.append(t("tree.indexed_hover").format(title=row['title'], category=row['freshness_category'], crawled_text=row['last_crawl_text'], url=row['url'], url_short=row['url'][:50]))

                st.markdown("---")
                st.subheader(t("tree.chart_title"))
                with st.expander(t("tree.how_to_navigate")):
                    st.markdown(f"{t('navigation_help_title')}\n{t('navigation_help_1')}\n{t('navigation_help_2')}\n{t('navigation_help_3')}")
                    st.markdown(f"{t('color_code_title')}\n{t('color_code_1')}\n{t('color_code_2')}\n{t('color_code_3')}\n{t('color_code_4')}\n{t('color_code_5')}")
                    st.markdown(f"{t('tip_title')}\n{t('tip_text')}")

                st.info(t("tree.zoom_tip"))
                
                fig_class = go.Treemap if viz_type == "TreeMap" else go.Sunburst if viz_type == "Sunburst" else go.Icicle
                zoom_tip_key = f"tree.{viz_type.lower()}_zoom_tip"
                
                fig = go.Figure(fig_class(
                    labels=labels, parents=parents, values=values, ids=ids, branchvalues="total",
                    marker={
                        'colors': colors, 'colorscale': [[0,'#22c55e'],[0.05,'#84cc16'],[0.2,'#eab308'],[0.4,'#f97316'],[0.6,'#ef4444'],[1,'#4b5563']],
                        'cmid': 45, 'cmin': 0, 'cmax': 181,
                        'colorbar': {'title': t("tree.colorbar_title"), 'tickvals': [0, 7, 30, 90, 180], 'ticktext': [t('tree.today'), f'7{t("tree.days_abbr")}', f'30{t("tree.days_abbr")}', f'90{t("tree.days_abbr")}', f'180{t("tree.days_abbr")}+']}
                    },
                    text=labels, customdata=hover_texts, hovertemplate=t("tree.hover_size")
                ))
                fig.update_layout(height=800, margin=dict(t=50, l=10, r=10, b=10), title={'text': t(zoom_tip_key), 'x': 0.5, 'xanchor': 'center', 'font': {'size': 14, 'color': '#666'}}, hoverlabel={'bgcolor':"white", 'font_size':13, 'font_family':"Arial"})
                st.plotly_chart(fig, use_container_width=True)

                st.markdown("---")
                st.subheader(t("tree.freshness_dist_title"))
                category_order = [t("tree.indexed_today"), t("tree.indexed_this_week"), t("tree.indexed_this_month"), t("tree.indexed_1_3_months"), t("tree.indexed_3_plus_months"), t("tree.unknown_date"), t("tree.pending_status")]
                color_map = {cat: color for cat, color in zip(category_order, ["#22c55e", "#84cc16", "#eab308", "#f97316", "#ef4444", "#6b7280", "#4b5563"])}
                freshness_counts = df['freshness_category'].value_counts().reindex(category_order, fill_value=0)
                freshness_df = pd.DataFrame({t("tree.category"): freshness_counts.index, t("tree.count"): freshness_counts.values})
                fig_freshness = px.bar(freshness_df, x=t("tree.category"), y=t("tree.count"), title=t("tree.freshness_chart_title"), color=t("tree.category"), color_discrete_map=color_map)
                fig_freshness.update_layout(height=400, showlegend=False, xaxis_title="", yaxis_title=t("tree.page_count"))
                st.plotly_chart(fig_freshness, use_container_width=True)

                st.markdown("---")
                col1, col2 = st.columns(2)
                with col1:
                    st.subheader(t("tree.priority_recrawl_title")); st.caption(t("tree.priority_recrawl_caption"))
                    df['priority_score'] = df['last_crawl_days'] * 0.7 + df['freshness_days'] * 0.3
                    old_pages = df[df['status'] == 'indexed'].nlargest(10, 'priority_score')
                    if not old_pages.empty:
                        old_pages.columns = [t("tree.col_title"), t("tree.col_site"), 'Jours crawl', 'Jours index', t("tree.col_last_visit"), t("tree.col_status")] # Simplified for display
                        st.dataframe(old_pages[['Titre', 'Site', 'Jours crawl', 'Jours index']], use_container_width=True, hide_index=True, height=400)
                    else: st.info(t("tree.all_pages_up_to_date"))
                with col2:
                    st.subheader(t("tree.recently_crawled_title")); st.caption(t("tree.recently_crawled_caption"))
                    recent_pages = df.nsmallest(10, 'last_crawl_days')
                    if not recent_pages.empty:
                        recent_pages.columns = [t("tree.col_title"), t("tree.col_site"), 'Jours crawl', 'Jours index', t("tree.col_last_visit"), t("tree.col_status")] # Simplified
                        st.dataframe(recent_pages[['Titre', 'Site', 'Jours crawl', 'Jours index']], use_container_width=True, hide_index=True, height=400)
                    else: st.info(t("tree.no_recent_crawls"))

                st.markdown("---")
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button(label=t("tree.export_button"), data=csv, file_name=f"indexation_analysis_{datetime.now().strftime('%Y%m%d')}.csv", mime="text/csv")

    except Exception as e:
        st.error(t("tree.error_viz").format(e=e))
        st.exception(e)

if running:
    st.markdown("---")
    st.caption(t("tree.auto_refresh_caption_30s"))
    time.sleep(30)
    st.rerun()

#!/usr/bin/env python3
"""
Script de diagnostic rapide pour vérifier l'état de l'indexation MeiliSearch
"""

import os
from dotenv import load_dotenv
import meilisearch
from datetime import datetime

load_dotenv()

MEILI_URL = os.getenv("MEILI_URL")
MEILI_KEY = os.getenv("MEILI_KEY")
INDEX_NAME = os.getenv("INDEX_NAME", "kidsearch")


def check_status():
    print("=" * 60)
    print("🔍 DIAGNOSTIC MEILISEARCH")
    print("=" * 60)

    try:
        client = meilisearch.Client(MEILI_URL, MEILI_KEY)
        index = client.index(INDEX_NAME)

        # 1. Statistiques de l'index
        print(f"\n📊 Index: {INDEX_NAME}")
        stats = index.get_stats()
        print(f"   Documents indexés: {stats.number_of_documents:,}")
        print(f"   Indexation en cours: {'Oui' if stats.is_indexing else 'Non'}")

        # 2. Tâches en attente
        print("\n⏳ Tâches en attente:")
        try:
            import requests
            headers = {"Authorization": f"Bearer {MEILI_KEY}"}
            response = requests.get(
                f"{MEILI_URL}/tasks",
                params={
                    'indexUids': INDEX_NAME,
                    'statuses': 'enqueued,processing',
                    'limit': 20
                },
                headers=headers
            )
            pending_data = response.json()
            pending_total = pending_data.get('total', 0)
            pending_results = pending_data.get('results', [])

            print(f"   Total: {pending_total}")

            if pending_total > 0:
                print("\n   Détails:")
                for task in pending_results[:5]:
                    task_type = task.get('type', 'unknown')
                    status = task.get('status', 'unknown')
                    uid = task.get('uid', '?')
                    print(f"   - Task #{uid}: {task_type} [{status}]")
        except Exception as e:
            print(f"   ⚠️  Erreur lecture tâches en attente: {e}")

        # 3. Dernières tâches terminées
        print("\n✅ Dernières tâches terminées:")
        try:
            response = requests.get(
                f"{MEILI_URL}/tasks",
                params={
                    'indexUids': INDEX_NAME,
                    'statuses': 'succeeded,failed',
                    'limit': 5
                },
                headers=headers
            )
            completed_data = response.json()
            completed_results = completed_data.get('results', [])

            for task in completed_results:
                status = task.get('status', 'unknown')
                status_icon = "✅" if status == "succeeded" else "❌"
                task_type = task.get('type', 'unknown')
                uid = task.get('uid', '?')

                # Extraire le nombre de documents si disponible
                details = ""
                task_details = task.get('details', {})
                if task_details and 'receivedDocuments' in task_details:
                    details = f" ({task_details['receivedDocuments']} docs)"

                print(f"   {status_icon} Task #{uid}: {task_type}{details}")
        except Exception as e:
            print(f"   ⚠️  Erreur lecture tâches terminées: {e}")

        # 4. Distribution par site
        print("\n🌐 Distribution par site:")
        try:
            result = index.search("", {'facets': ['site'], 'limit': 0})
            if 'facetDistribution' in result and 'site' in result['facetDistribution']:
                sites = result['facetDistribution']['site']
                for site, count in sorted(sites.items(), key=lambda x: x[1], reverse=True):
                    print(f"   - {site}: {count:,} documents")
            else:
                print("   Aucune distribution disponible (facet 'site' non configurée?)")
        except Exception as e:
            print(f"   ⚠️  Erreur: {e}")

        # 5. Vérification des embeddings
        print("\n🤖 Embeddings:")
        try:
            with_vectors = index.search("", {'filter': '_vectors.default EXISTS', 'limit': 0})
            without_vectors = index.search("", {'filter': '_vectors.default NOT EXISTS', 'limit': 0})

            total = with_vectors.get('estimatedTotalHits', 0) + without_vectors.get('estimatedTotalHits', 0)
            with_count = with_vectors.get('estimatedTotalHits', 0)
            without_count = without_vectors.get('estimatedTotalHits', 0)

            print(f"   Avec embeddings: {with_count:,}")
            print(f"   Sans embeddings: {without_count:,}")
            if total > 0:
                completion = (with_count / total) * 100
                print(f"   Complétion: {completion:.1f}%")
        except Exception as e:
            print(f"   ⚠️  Erreur: {e}")

        print("\n" + "=" * 60)

    except Exception as e:
        print(f"\n❌ ERREUR: {e}")
        import traceback
        print(traceback.format_exc())


if __name__ == "__main__":
    check_status()
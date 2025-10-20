#!/usr/bin/env python3
"""
Script de diagnostic rapide pour vérifier l'état de l'indexation MeiliSearch
"""

import os
from dotenv import load_dotenv
from meilisearch_python_sdk import Client

load_dotenv()

MEILI_URL = os.getenv("MEILI_URL")
MEILI_KEY = os.getenv("MEILI_KEY")
INDEX_NAME = os.getenv("INDEX_NAME", "kidsearch")


def check_status():
    print("=" * 60)
    print("🔍 DIAGNOSTIC MEILISEARCH")
    print("=" * 60)

    try:
        client = Client(url=MEILI_URL, api_key=MEILI_KEY)
        index = client.index(INDEX_NAME)

        # 1. Statistiques de l'index
        print(f"\n📊 Index: {INDEX_NAME}")
        stats = index.get_stats()
        print(f"   Documents indexés: {stats.number_of_documents:,}")
        print(f"   Indexation en cours: {'Oui' if stats.is_indexing else 'Non'}")

        # 2. Tâches en attente
        print("\n⏳ Tâches en attente:")
        try:
            pending_tasks = client.get_tasks(index_ids=[INDEX_NAME], statuses=['enqueued', 'processing'], limit=20)
            print(f"   Total: {pending_tasks.total}")

            if pending_tasks.total > 0:
                print("\n   Détails:")
                for task in pending_tasks.results[:5]:
                    print(f"   - Task #{task.uid}: {task.type} [{task.status}]")
        except Exception as e:
            print(f"   ⚠️  Erreur lecture tâches en attente: {e}")

        # 3. Dernières tâches terminées
        print("\n✅ Dernières tâches terminées:")
        try:
            completed_tasks = client.get_tasks(index_ids=[INDEX_NAME], statuses=['succeeded', 'failed'], limit=5)
            for task in completed_tasks.results:
                status_icon = "✅" if task.status == "succeeded" else "❌"
                details = ""
                if task.details and task.details.get('receivedDocuments'):
                    details = f" ({task.details['receivedDocuments']} docs)"
                print(f"   {status_icon} Task #{task.uid}: {task.type}{details}")
        except Exception as e:
            print(f"   ⚠️  Erreur lecture tâches terminées: {e}")

        # 4. Distribution par site
        print("\n🌐 Distribution par site:")
        try:
            result = index.search("", facets=['site'], limit=0)
            if result.facet_distribution and 'site' in result.facet_distribution:
                sites = result.facet_distribution['site']
                for site, count in sorted(sites.items(), key=lambda x: x[1], reverse=True):
                    print(f"   - {site}: {count:,} documents")
            else:
                print("   Aucune distribution disponible (facet 'site' non configurée?)")
        except Exception as e:
            print(f"   ⚠️  Erreur: {e}")

        # 5. Vérification des embeddings
        print("\n🤖 Embeddings:")
        try:
            with_vectors = index.search("", filter='_vectors.default EXISTS', limit=0)
            without_vectors = index.search("", filter='_vectors.default NOT EXISTS', limit=0)

            total = with_vectors.estimated_total_hits + without_vectors.estimated_total_hits
            with_count = with_vectors.estimated_total_hits
            without_count = without_vectors.estimated_total_hits

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

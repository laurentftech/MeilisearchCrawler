import requests
from meilisearch import Client
import json
import os
from dotenv import load_dotenv

# ---------------------------
# Load environment variables
# ---------------------------
load_dotenv()

# ---------------------------
# Configuration
# ---------------------------
MEILI_URL = os.getenv("MEILI_URL")
MEILI_KEY = os.getenv("MEILI_KEY")
INDEX_NAME = "kidsearch"

if not MEILI_URL or not MEILI_KEY:
    print("❌ MEILI_URL and MEILI_KEY environment variables must be set.")
    print("   Create a .env file from .env.example and fill in the values.")
    exit(1)

def test_meilisearch_connection():
    """Test 1: Check connection to MeiliSearch"""
    print("🔍 Test 1: MeiliSearch Connection")
    try:
        client = Client(MEILI_URL, MEILI_KEY)
        health = client.health()
        print(f"✅ MeiliSearch is online: {health}")
        return client
    except Exception as e:
        print(f"❌ Connection error: {e}")
        return None


def test_index_exists(client):
    """Test 2: Check if the index exists"""
    print("\n🔍 Test 2: Index Verification")
    try:
        indexes = client.get_indexes()
        existing_indexes = [i.uid for i in indexes['results']]

        if INDEX_NAME in existing_indexes:
            print(f"✅ Index '{INDEX_NAME}' found")
            return client.index(INDEX_NAME)
        else:
            print(f"❌ Index '{INDEX_NAME}' not found")
            print(f"Available indexes: {existing_indexes}")
            return None
    except Exception as e:
        print(f"❌ Error: {e}")
        return None


def test_documents_count(index):
    """Test 3: Count documents"""
    print("\n🔍 Test 3: Document Count")
    try:
        stats = index.get_stats()
        count = stats.number_of_documents
        print(f"📊 Number of documents: {count}")

        if count > 0:
            print("✅ Documents have been indexed")
            return True
        else:
            print("⚠️ No documents indexed")
            return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_search_functionality(index):
    """Test 4: Test search functionality"""
    print("\n🔍 Test 4: Search Test")

    # Quelques requêtes de test
    test_queries = ["child", "game", "animal", "school", "story"]

    for query in test_queries:
        try:
            results = index.search(query, {"limit": 3})
            hits = results['hits']
            print(f"🔎 '{query}': {len(hits)} results")

            if hits:
                print(f"   First result: {hits[0]['title'][:50]}...")
                return True

        except Exception as e:
            print(f"❌ Search error for '{query}': {e}")

    return False


def test_specific_search(index, query=""):
    """Test 5: Specific search with details"""
    if not query:
        query = input("\n🔎 Enter a search query to test: ")

    print(f"\n🔍 Test 5: Detailed search for '{query}'")

    try:
        results = index.search(query, {
            "limit": 5,
            "attributesToHighlight": ["title", "content"],
            "highlightPreTag": "**",
            "highlightPostTag": "**"
        })

        print(f"📊 Found {results['estimatedTotalHits']} results")
        print(f"⏱️ Search took {results['processingTimeMs']}ms")

        for i, hit in enumerate(results['hits'], 1):
            print(f"\n--- Result {i} ---")
            print(f"Site: {hit['site']}")
            print(f"URL: {hit['url']}")
            print(f"Title: {hit['title']}")
            print(f"Content: {hit['content'][:200]}...")

            # Afficher les highlights si disponibles
            if '_formatted' in hit:
                if 'title' in hit['_formatted']:
                    print(f"Highlighted Title: {hit['_formatted']['title']}")

        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_api_directly():
    """Test 6: Direct REST API test"""
    print("\n🔍 Test 6: Direct REST API Test")

    try:
        # Test de santé
        health_url = f"{MEILI_URL}/health"
        response = requests.get(health_url)
        print(f"✅ API Health: {response.status_code}")

        # Test recherche directe
        search_url = f"{MEILI_URL}/indexes/{INDEX_NAME}/search"
        headers = {"Authorization": f"Bearer {MEILI_KEY}"}
        payload = {"q": "test", "limit": 1}

        response = requests.post(search_url, headers=headers, json=payload)
        print(f"✅ API Search: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print(f"📊 API Results: {len(data.get('hits', []))} documents")
            return True

    except Exception as e:
        print(f"❌ API Error: {e}")
        return False


def show_sample_documents(index, limit=3):
    """Test 7: Display sample documents"""
    print(f"\n🔍 Test 7: Sample of {limit} documents")

    try:
        # Recherche vide pour récupérer tous les documents
        results = index.search("", {"limit": limit})

        for i, doc in enumerate(results['hits'], 1):
            print(f"\n--- Document {i} ---")
            print(f"ID: {doc['id']}")
            print(f"Site: {doc['site']}")
            print(f"URL: {doc['url']}")
            print(f"Title: {doc['title']}")
            print(f"Content: {doc['content'][:100]}...")

    except Exception as e:
        print(f"❌ Error: {e}")


def interactive_search(index):
    """Test 8: Interactive search mode"""
    print("\n🔍 Test 8: Interactive Search Mode")
    print("Type 'quit' to exit")

    while True:
        query = input("\n🔎 Search: ").strip()

        if query.lower() in ['quit', 'exit', 'q']:
            break

        if not query:
            continue

        try:
            results = index.search(query, {"limit": 3})
            print(f"📊 {len(results['hits'])} results found:")

            for i, hit in enumerate(results['hits'], 1):
                print(f"{i}. {hit['title']} - {hit['site']}")
                print(f"   {hit['url']}")

        except Exception as e:
            print(f"❌ Error: {e}")


# ---------------------------
# Main
# ---------------------------
def main():
    print("🧪 MeiliSearch Crawler Tests")
    print("=" * 40)

    # Test 1: Connexion
    client = test_meilisearch_connection()
    if not client:
        return

    # Test 2: Index
    index = test_index_exists(client)
    if not index:
        return

    # Test 3: Documents
    has_documents = test_documents_count(index)

    # Test 4: Recherche basique
    search_works = test_search_functionality(index)

    # Test 5: Recherche détaillée
    if has_documents and search_works:
        test_specific_search(index, "child")

    # Test 6: API directe
    test_api_directly()

    # Test 7: Échantillons
    if has_documents:
        show_sample_documents(index)

    # Test 8: Mode interactif (optionnel)
    user_choice = input("\n🤔 Do you want to try interactive search? (y/n): ")
    if user_choice.lower() in ['y', 'yes']:
        interactive_search(index)

    print("\n🎉 Tests finished!")


if __name__ == "__main__":
    main()
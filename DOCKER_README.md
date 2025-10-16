# KidSearch - Docker Deployment Guide

This guide explains how to deploy KidSearch Dashboard and API using Docker.

## Quick Start

### 1. Prerequisites

- Docker Engine 20.10+
- Docker Compose 2.0+
- At least 2GB free RAM

### 2. Configuration

Copy the example environment file:

```bash
cp .env.example .env
```

Edit `.env` and configure:

```bash
# Meilisearch
MEILI_URL=http://meilisearch:7700
MEILI_KEY=masterKey
INDEX_NAME=kidsearch

# API Configuration
API_ENABLED=true
API_HOST=0.0.0.0
API_PORT=8080
API_WORKERS=4

# Dashboard Configuration
DASHBOARD_HOST=0.0.0.0
DASHBOARD_PORT=8501

# Optional: Google CSE (for broader search results)
GOOGLE_CSE_API_KEY=your_api_key_here
GOOGLE_CSE_ID=your_search_engine_id_here

# Optional: Google Gemini (for embeddings)
GOOGLE_GEMINI_API_KEY=your_gemini_api_key_here

# Optional: Semantic Reranking
RERANKING_ENABLED=false
RERANKER_MODEL=Snowflake/snowflake-arctic-embed-m
```

### 3. Start Services

**Option A: All-in-One (Dashboard + API)**

```bash
docker-compose up -d
```

This starts:
- Meilisearch on port 7700
- Dashboard on port 8501
- API on port 8080

**Option B: Separate Services**

Edit `docker-compose.yml` and uncomment the separate services:

```bash
# Disable kidsearch-all
# Enable kidsearch-dashboard and kidsearch-api

docker-compose up -d kidsearch-dashboard kidsearch-api
```

### 4. Access Services

- **Dashboard**: http://localhost:8501
- **API Documentation**: http://localhost:8080/api/docs
- **API ReDoc**: http://localhost:8080/api/redoc
- **Meilisearch**: http://localhost:7700

### 5. Initial Setup

After starting, create the Meilisearch index:

```bash
# Access the container
docker exec -it kidsearch-all bash

# Create index
python create_index.py

# Run initial crawl
python crawler.py
```

## Service Modes

The Docker image supports three service modes via the `SERVICE` environment variable:

### Mode 1: All-in-One (default)

```yaml
environment:
  SERVICE: all
```

Runs both Dashboard and API in a single container.

**Pros:**
- Simple deployment
- Lower resource usage
- Single container to manage

**Cons:**
- Both services restart together
- Scaling requires scaling both

### Mode 2: Dashboard Only

```yaml
environment:
  SERVICE: dashboard
```

Runs only the Streamlit Dashboard.

**Use case:** Monitoring and management interface only.

### Mode 3: API Only

```yaml
environment:
  SERVICE: api
```

Runs only the FastAPI backend.

**Use case:** Production search API without dashboard.

## Advanced Configuration

### Custom Ports

```yaml
ports:
  - "8502:8501"  # Custom dashboard port
  - "8081:8080"  # Custom API port
environment:
  DASHBOARD_PORT: 8501
  API_PORT: 8080
```

### Resource Limits

Add resource constraints:

```yaml
deploy:
  resources:
    limits:
      cpus: '2.0'
      memory: 4G
    reservations:
      cpus: '1.0'
      memory: 2G
```

### Persistent Data

Data is stored in volumes:

```yaml
volumes:
  - ./data:/app/data          # Cache, logs, stats
  - ./config:/app/config      # Site configuration
  - meilisearch-data:/meili_data  # Search index
```

### Enable Reranking

To use semantic reranking, you need to rebuild the image with PyTorch:

1. Edit `Dockerfile` and uncomment:

```dockerfile
RUN pip install --no-cache-dir -r requirements-reranking.txt
```

2. Rebuild:

```bash
docker-compose build --no-cache
```

3. Update `.env`:

```bash
RERANKING_ENABLED=true
RERANKER_MODEL=Snowflake/snowflake-arctic-embed-m
```

**Note:** Reranking adds ~2GB to image size and requires more RAM.

## Management Commands

### View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f kidsearch-all

# API logs only
docker-compose logs -f kidsearch-all | grep "api"
```

### Restart Services

```bash
# Restart all
docker-compose restart

# Restart specific service
docker-compose restart kidsearch-all
```

### Stop Services

```bash
docker-compose down
```

### Clean Everything (including data)

```bash
docker-compose down -v
```

### Update to Latest Code

```bash
git pull
docker-compose build --no-cache
docker-compose up -d
```

### Run Crawler in Container

```bash
# Interactive
docker exec -it kidsearch-all python crawler.py

# Background with all sites
docker exec -d kidsearch-all python crawler.py --workers 10

# Specific site
docker exec -d kidsearch-all python crawler.py --site "Vikidia"

# With embeddings
docker exec -d kidsearch-all python crawler.py --embeddings
```

## Monitoring

### Health Checks

Docker includes built-in health checks:

```bash
docker ps
```

Look for status: `healthy` or `unhealthy`

### Resource Usage

```bash
docker stats kidsearch-all
```

### Database Size

```bash
# Meilisearch index size
docker exec kidsearch-all du -sh /app/data/

# Cache database size
docker exec kidsearch-all ls -lh /app/data/crawler_cache.db
```

## Troubleshooting

### Service won't start

Check logs:

```bash
docker-compose logs kidsearch-all
```

### Dashboard not accessible

1. Check if port is already in use:

```bash
lsof -i :8501
```

2. Try a different port in `docker-compose.yml`

### API not responding

1. Verify API is enabled:

```bash
docker exec kidsearch-all env | grep API_ENABLED
```

2. Check Meilisearch connection:

```bash
docker exec kidsearch-all curl http://meilisearch:7700/health
```

### Container crashes / Out of memory

Increase Docker memory limit:

```bash
# Check current usage
docker stats

# Edit docker-compose.yml and add memory limits
```

### Slow performance

1. Increase API workers:

```yaml
environment:
  API_WORKERS: 8
```

2. Enable caching:

```bash
CACHE_DAYS=7
```

3. Check Meilisearch index size - consider reducing indexed content.

## Production Deployment

### Security

1. **Change default keys:**

```bash
# Generate secure key
openssl rand -base64 32

# Update .env
MEILI_KEY=<generated_key>
```

2. **Use HTTPS:**

Consider using a reverse proxy (nginx, Traefik, Caddy) with SSL certificates.

3. **Restrict CORS:**

Edit `meilisearchcrawler/api/server.py`:

```python
allow_origins=["https://yourdomain.com"]
```

### Backup

**Backup Meilisearch data:**

```bash
docker exec kidsearch-meilisearch sh -c 'tar czf - /meili_data' > backup-meili-$(date +%Y%m%d).tar.gz
```

**Backup crawler data:**

```bash
tar czf backup-data-$(date +%Y%m%d).tar.gz data/
```

**Restore:**

```bash
# Stop services
docker-compose down

# Restore data
tar xzf backup-data-YYYYMMDD.tar.gz

# Restart
docker-compose up -d
```

### Scaling

For high-traffic deployments:

1. **Separate services** - Use dashboard and API in separate containers
2. **Multiple API workers** - Increase `API_WORKERS`
3. **Load balancer** - Add nginx/HAProxy in front of API containers
4. **Read replicas** - Meilisearch supports read replicas (experimental)

## Integration with Existing Infrastructure

### External Meilisearch

If you already have Meilisearch running:

1. Comment out the `meilisearch` service in `docker-compose.yml`

2. Update `.env`:

```bash
MEILI_URL=http://your-meilisearch-host:7700
MEILI_KEY=your_master_key
```

### Kubernetes

For Kubernetes deployment, see `k8s/` directory (coming soon).

## Environment Variables Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVICE` | `all` | Service mode: `all`, `dashboard`, or `api` |
| `DASHBOARD_PORT` | `8501` | Dashboard port |
| `DASHBOARD_HOST` | `0.0.0.0` | Dashboard host |
| `API_PORT` | `8080` | API port |
| `API_HOST` | `0.0.0.0` | API host |
| `API_WORKERS` | `4` | Number of API worker processes |
| `API_ENABLED` | `true` | Enable/disable API |
| `MEILI_URL` | `http://localhost:7700` | Meilisearch URL |
| `MEILI_KEY` | - | Meilisearch master key |
| `INDEX_NAME` | `kidsearch` | Meilisearch index name |
| `RERANKING_ENABLED` | `false` | Enable semantic reranking |
| `RERANKER_MODEL` | `snowflake-arctic-embed-m` | Reranking model |
| `GOOGLE_CSE_API_KEY` | - | Google CSE API key (optional) |
| `GOOGLE_CSE_ID` | - | Google CSE ID (optional) |
| `GOOGLE_GEMINI_API_KEY` | - | Gemini API key (optional) |

## Support

For issues and questions:

- GitHub Issues: [your-repo/issues](https://github.com/your-repo/issues)
- Documentation: [CLAUDE.md](./CLAUDE.md)
- API Documentation: http://localhost:8080/api/docs

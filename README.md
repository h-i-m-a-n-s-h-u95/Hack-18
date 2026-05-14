# 🎪 Ringmaster Round Table v2.0

**AI-Powered Travel Planning with Redis-Orchestrated Multi-Agent System**

## 🚀 What's New in v2.0

### Redis MCP Architecture
- **Parallel Agent Execution**: All 5 agents run simultaneously via Redis pub/sub for 3-5x faster responses
- **Real-time Streaming Updates**: Live progress notifications as each agent completes its work
- **Horizontally Scalable Workers**: Each agent runs in isolated Docker containers with configurable replicas
- **Session State Management**: Resume planning sessions, track progress, cancel ongoing requests
- **Fault Tolerance**: Graceful degradation when individual agents fail
- **Health Monitoring**: Real-time agent performance tracking and availability checks

### Enhanced Orchestrator
- **Stateless Design**: All state persisted in Redis with configurable TTL (default 1 hour)
- **Message-based Protocol (MCP)**: Standardized request/response format across all agents
- **Timeout Management**: Configurable per-agent timeouts with automatic fallback
- **Load Balancing**: Multiple worker replicas handle requests in parallel
- **Structured Data Extraction**: LLM responses parsed into JSON for rich UI rendering

---

## 📁 Project Structure

```
ringmaster-round-table/
├── app/
│   ├── main.py                        # FastAPI application entry point
│   │
│   ├── config/
│   │   └── settings.py                # Configuration with Redis & timeouts
│   │
│   ├── core/
│   │   ├── state.py                   # TravelState & data models
│   │   └── orchestrator.py            # Redis-based orchestrator
│   │
│   ├── messaging/
│   │   ├── redis_client.py            # Redis pub/sub client manager
│   │   └── protocols.py               # MCP message schemas & validation
│   │
│   ├── agents/
│   │   ├── base_agent.py              # BaseAgent with MCP support
│   │   ├── weather_agent.py           # Sky Gazer (OpenWeather API)
│   │   ├── events_agent.py            # Event Explorer (OpenWeb Ninja)
│   │   ├── maps_agent.py              # Trailblazer (OpenRouteService)
│   │   ├── budget_agent.py            # Quartermaster (budget analysis)
│   │   └── itinerary_agent.py         # Itinerary Weaver (day planner)
│   │
│   ├── workers/
│   │   ├── weather_worker.py          # Weather worker process
│   │   ├── events_worker.py           # Events worker process
│   │   ├── maps_worker.py             # Maps worker process
│   │   ├── budget_worker.py           # Budget worker process
│   │   └── itinerary_worker.py        # Itinerary worker process
│   │
│   ├── services/
│   │   ├── weather_service.py         # OpenWeather API integration
│   │   ├── event_service.py           # OpenWeb Ninja API integration
│   │   ├── maps_service.py            # OpenRouteService integration
│   │   ├── budget_service.py          # Budget calculation logic
│   │   └── itinerary_service.py       # Itinerary generation logic
│   │
│   └── api/
│       └── routes.py                  # FastAPI routes (v1 & v2)
│
├── deployment/
│   └── docker/
│       ├── Dockerfile                 # API service container
│       └── Dockerfile.worker          # Worker container (shared)
│
├── requirements.txt                   # Python dependencies
├── docker-compose.yml                 # Multi-container orchestration
├── .env.example                       # Environment template
└── README.md                          # This file
```

---

## 🛠️ Setup Instructions

### 1. Prerequisites

- **Python 3.11+**
- **Docker & Docker Compose** (for containerized deployment)
- **Upstash Redis** account (free tier available at https://upstash.com)

### 2. Get API Keys

#### Required APIs:
- **Google Gemini AI**: https://makersuite.google.com/app/apikey
- **OpenWeather API**: https://openweathermap.org/api (free tier: 1000 calls/day)
- **OpenRouteService**: https://openrouteservice.org/dev/#/signup (free tier: 2000 req/day)
- **Upstash Redis**: https://console.upstash.com/ (free tier: 10k commands/day)

#### Optional APIs:
- **OpenWeb Ninja**: https://openwebninja.com (for real-time event data)

### 3. Environment Setup

```bash
# Clone the repository
git clone https://github.com/yourusername/ringmaster-round-table.git
cd ringmaster-round-table

# Copy environment template
cp .env.example .env

# Edit .env with your API keys
nano .env
```

**Critical `.env` variables:**

```bash
# Google Gemini (Required)
GOOGLE_API_KEY=your_gemini_api_key_here

# Weather Data (Required)
OPENWEATHER_API_KEY=your_openweather_key_here

# Maps & Routing (Required)
OPENROUTE_API_KEY=your_openroute_key_here

# Redis (Required - Get from Upstash Console)
REDIS_URL=redis://default:your_password@your-endpoint.upstash.io:6379

# Events (Optional)
OPENWEB_NINJA_API_KEY=your_openweb_key_here

# Configuration
DEBUG=true
STREAMING_ENABLED=true
MODEL_NAME=gemini-1.5-pro
TEMPERATURE=0.7
```

### 4. Installation

#### Option A: Docker (Recommended)

```bash
# Build and start all services
docker-compose up --build

# Run in detached mode
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down

# Scale workers for high load
docker-compose up --scale weather-worker=3 --scale events-worker=3
```

**What gets started:**
- 1x API service (port 8000)
- 2x Weather workers
- 2x Events workers
- 2x Maps workers
- 1x Budget worker
- 1x Itinerary worker

#### Option B: Local Development

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Terminal 1: Start API
python -m uvicorn app.main:app --reload

# Terminal 2-6: Start workers
python -m app.workers.weather_worker
python -m app.workers.events_worker
python -m app.workers.maps_worker
python -m app.workers.budget_worker
python -m app.workers.itinerary_worker
```

---

## 🎯 API Usage

### Interactive Documentation

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Health Check**: http://localhost:8000/health

### Main Endpoint: Plan Complete Trip (v2)

**POST** `/api/v1/plan-trip`

Plans a complete trip using parallel agent execution.

```bash
curl -X POST "http://localhost:8000/api/v1/plan-trip" \
  -H "Content-Type: application/json" \
  -d '{
    "destination": "Paris, France",
    "origin": "New Delhi, India",
    "travel_dates": ["2025-07-01", "2025-07-02", "2025-07-03"],
    "travelers_count": 2,
    "budget_range": "mid-range",
    "user_preferences": {
      "interests": ["art", "food", "history"],
      "pace": "moderate"
    }
  }'
```

**Request Body:**
```json
{
  "destination": "string (required)",
  "origin": "string (required)",
  "travel_dates": ["YYYY-MM-DD", "..."] (required),
  "travelers_count": 1 (required),
  "budget_range": "budget|mid-range|luxury",
  "preferred_transport": "driving|walking|cycling",
  "user_preferences": {
    "interests": ["culture", "adventure", "food"],
    "pace": "relaxed|moderate|fast"
  }
}
```

**Response (200 OK):**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "message": "Trip planning completed successfully",
  "data": {
    "weather": {
      "weather_forecast": [...],
      "weather_summary": "Expect warm sunny days...",
      "average_temp_range": {"min": 15, "max": 25}
    },
    "events": {
      "events": [...],
      "event_summary": "3 major events during your visit...",
      "free_events": [...]
    },
    "route": {
      "primary_route": {...},
      "alternative_routes": {...},
      "route_analysis": "Flying is recommended..."
    },
    "budget": {
      "budget_breakdown": {
        "total": 50000,
        "transportation": 20000,
        "accommodation": 15000,
        "food": 10000,
        "activities": 5000
      },
      "cost_per_person": 25000
    },
    "itinerary": {
      "itinerary_days": [...],
      "transport_details": {...},
      "key_tips": [...]
    }
  },
  "processing_time_ms": 5234,
  "agents_completed": ["weather", "events", "maps", "budget", "itinerary"],
  "agents_failed": []
}
```

### Real-time Streaming (Server-Sent Events)

**GET** `/api/v1/plan-trip/stream`

Get live updates as agents complete their work.

```bash
curl -N "http://localhost:8000/api/v1/plan-trip/stream" \
  -H "Content-Type: application/json" \
  -d '{
    "destination": "Paris, France",
    "origin": "New Delhi, India",
    "travel_dates": ["2025-07-01", "2025-07-03"]
  }'
```

**SSE Stream:**
```
data: {"type":"started","session_id":"abc-123","timestamp":"2025-01-15T10:00:00Z"}

data: {"type":"progress","agent":"weather","message":"Fetching weather forecast","progress_percent":30}

data: {"type":"progress","agent":"weather","message":"Weather agent completed","progress_percent":100}

data: {"type":"progress","agent":"events","message":"Searching events in Paris","progress_percent":50}

data: {"type":"completed","status":"completed","data":{...}}
```

### Session Management

**Get Session Status**
```bash
GET /api/v1/session/{session_id}
```

**Cancel Session**
```bash
DELETE /api/v1/session/{session_id}
```

### Individual Agent Endpoints

These endpoints bypass the orchestrator and call agents directly:

**Weather Data**
```bash
POST /api/v1/weather
{
  "location": "Paris, France",
  "dates": ["2025-07-01", "2025-07-02"]
}
```

**Popular Events**
```bash
GET /api/v1/events/popular/{location}?limit=10
```

**Route Comparison**
```bash
GET /api/v1/route/compare/{origin}/{destination}
```

**Budget Estimation**
```bash
POST /api/v1/budget
{
  "destination": "Paris",
  "travelers_count": 2,
  "days": 3
}
```

---

## 🏗️ Architecture Deep Dive

### Redis MCP (Message Communication Protocol)

```
┌─────────────────────────────────────────────────┐
│          FastAPI Orchestrator (API)              │
│  - Receives user request                         │
│  - Generates session_id                          │
│  - Fans out to worker queues                     │
│  - Aggregates responses                          │
└─────────────────┬───────────────────────────────┘
                  │
                  │ Redis Pub/Sub
                  │
      ┌───────────┴───────────┐
      │                       │
      ▼                       ▼
┌─────────────┐         ┌─────────────┐
│   Request   │         │  Response   │
│  Channels   │         │  Channels   │
├─────────────┤         ├─────────────┤
│ weather:req │────────▶│weather:resp │
│ events:req  │────────▶│events:resp  │
│ maps:req    │────────▶│maps:resp    │
│ budget:req  │────────▶│budget:resp  │
└─────────────┘         └─────────────┘
      │                       │
      │                       │
      ▼                       ▼
┌─────────────────────────────────────┐
│          Worker Processes            │
│  ┌──────────────────────────────┐   │
│  │  Weather Worker (2 replicas) │   │
│  │  - Listens: weather:req      │   │
│  │  - Publishes: weather:resp   │   │
│  └──────────────────────────────┘   │
│  ┌──────────────────────────────┐   │
│  │  Events Worker (2 replicas)  │   │
│  └──────────────────────────────┘   │
│  ┌──────────────────────────────┐   │
│  │  Maps Worker (2 replicas)    │   │
│  └──────────────────────────────┘   │
│  ┌──────────────────────────────┐   │
│  │  Budget Worker (1 replica)   │   │
│  └──────────────────────────────┘   │
└─────────────────────────────────────┘
```

### Message Flow

1. **User Request** → API receives trip planning request
2. **Session Creation** → Orchestrator generates unique session_id
3. **State Persistence** → Initial state saved to Redis with TTL
4. **Fan-out** → Orchestrator publishes to 4 agent request channels simultaneously
5. **Parallel Processing** → Workers pick up requests and process independently
6. **Streaming Updates** → Workers publish progress to `streaming:update:{session_id}`
7. **Fan-in** → Orchestrator subscribes to response channels, waits for all agents
8. **Aggregation** → Responses collected with timeout handling
9. **Itinerary Generation** → Final agent synthesizes complete itinerary
10. **Response** → Complete travel plan returned to user

### MCP Message Schema

All messages follow this standardized format:

```python
{
  "session_id": "uuid",              # Unique session identifier
  "request_id": "uuid",              # Unique request identifier
  "timestamp": "ISO-8601",           # Message timestamp
  "agent": "weather|events|maps|...", # Agent type
  "action": "request|response|error", # Message action
  "payload": {                       # Agent-specific data
    "destination": "Paris",
    "travel_dates": [...]
  },
  "metadata": {
    "timeout_ms": 10000,             # Request timeout
    "retry_count": 0,                # Retry attempts
    "priority": "normal",            # Message priority
    "correlation_id": "uuid"         # For tracking chains
  }
}
```

### Redis Channel Structure

**Request Channels** (Orchestrator → Workers):
- `agent:weather:request` - Weather data requests
- `agent:events:request` - Event search requests
- `agent:maps:request` - Route planning requests
- `agent:budget:request` - Budget estimation requests
- `agent:itinerary:request` - Itinerary generation requests

**Response Channels** (Workers → Orchestrator):
- `agent:weather:response:{session_id}` - Session-specific responses
- `agent:events:response:{session_id}`
- `agent:maps:response:{session_id}`
- `agent:budget:response:{session_id}`
- `agent:itinerary:response:{session_id}`

**Streaming Channels**:
- `streaming:update:{session_id}` - Real-time progress updates

**Control Channels**:
- `agent:health` - Health check broadcasts
- `agent:cancel:{session_id}` - Cancellation signals

### State Management

All session state is stored in Redis:

```python
Key: "state:{session_id}"
TTL: 3600 seconds (1 hour)
Value: {
  "destination": "Paris",
  "origin": "New Delhi",
  "travel_dates": [...],
  "weather_data": {...},
  "events_data": [...],
  "route_data": {...},
  "budget_data": {...},
  "itinerary_data": [...]
}
```

---

## 🧪 Testing & Monitoring

### Health Checks

```bash
# Overall system health
curl http://localhost:8000/health

# Detailed status with Redis connection
curl http://localhost:8000/status

# Orchestrator-specific health
curl http://localhost:8000/api/v1/health
```

**Response:**
```json
{
  "status": "healthy",
  "redis_connected": true,
  "uptime_seconds": 3600,
  "agents": {
    "weather": "healthy",
    "events": "healthy",
    "maps": "healthy",
    "budget": "healthy",
    "itinerary": "healthy"
  }
}
```

### View Logs

```bash
# All services
docker-compose logs -f

# Specific worker
docker-compose logs -f weather-worker

# API only
docker-compose logs -f api

# Last 100 lines
docker-compose logs --tail=100
```

### Redis Monitoring

**Upstash Console**: https://console.upstash.com/

**Redis CLI**:
```bash
# Connect to Redis
redis-cli -u $REDIS_URL

# Monitor all commands
> MONITOR

# View keys
> KEYS state:*

# Check channel subscribers
> PUBSUB CHANNELS agent:*

# Get server info
> INFO
```

---

## ⚙️ Configuration

### Environment Variables

```bash
# Core Settings
DEBUG=true                    # Enable debug logging
HOST=0.0.0.0                 # API host
PORT=8000                    # API port

# Redis
REDIS_URL=redis://...        # Upstash Redis connection string
STREAMING_ENABLED=true       # Enable SSE streaming

# AI Model
MODEL_NAME=gemini-1.5-pro    # Google Gemini model
TEMPERATURE=0.7              # LLM temperature (0.0-1.0)
MAX_TOKENS=2048              # Max output tokens

# Agent Timeouts (milliseconds)
TIMEOUT_WEATHER=10000        # 10 seconds
TIMEOUT_EVENTS=15000         # 15 seconds
TIMEOUT_MAPS=12000           # 12 seconds
TIMEOUT_BUDGET=8000          # 8 seconds
TIMEOUT_ITINERARY=20000      # 20 seconds
ORCHESTRATOR_TIMEOUT=60000   # 60 seconds total

# State Management
STATE_TTL=3600               # Redis state TTL (seconds)
```

### Scaling Workers

```bash
# Scale up for high traffic
docker-compose up --scale weather-worker=5 --scale events-worker=5

# Scale down to save resources
docker-compose up --scale weather-worker=1 --scale events-worker=1

# Restart specific worker
docker-compose restart weather-worker
```

### Performance Tuning

**Redis Connection Pool**:
```python
# app/messaging/redis_client.py
max_connections=50           # Increase for high concurrency
socket_connect_timeout=5     # Connection timeout
health_check_interval=30     # Keep-alive checks
```

**Worker Replicas** (docker-compose.yml):
```yaml
weather-worker:
  deploy:
    replicas: 5              # More workers = higher throughput
```

---

## 🐛 Troubleshooting

### Redis Connection Failed

```
❌ Failed to connect to Redis: Connection refused
```

**Solutions:**
1. Verify `REDIS_URL` in `.env` is correct
2. Check Upstash Redis dashboard for service status
3. Test connection: `redis-cli -u $REDIS_URL ping`
4. Ensure firewall allows outbound connections to Upstash

### Workers Not Responding

```
⏱️ Timeout waiting for weather agent response
```

**Solutions:**
1. Check worker logs: `docker-compose logs weather-worker`
2. Verify workers are running: `docker-compose ps`
3. Restart workers: `docker-compose restart weather-worker`
4. Check Redis pub/sub: `redis-cli -u $REDIS_URL PUBSUB CHANNELS "agent:*"`

### Agent Timeout

```
Agent weather timed out after 10000ms
```

**Solutions:**
1. Increase timeout in `.env`: `TIMEOUT_WEATHER=20000`
2. Check external API status (OpenWeather, etc.)
3. Verify API keys are valid
4. Check worker CPU/memory usage

### Missing Dependencies

```
ModuleNotFoundError: No module named 'redis'
```

**Solution:**
```bash
pip install -r requirements.txt
```

### Port Already in Use

```
Error: port 8000 is already allocated
```

**Solutions:**
1. Change port: `PORT=8001` in `.env`
2. Stop conflicting process: `lsof -ti:8000 | xargs kill`
3. Use different port: `docker-compose -f docker-compose.yml up --build -d -e PORT=8001`

---

## 🚀 Production Deployment

### Environment Configuration

```bash
# Production .env
DEBUG=false
HOST=0.0.0.0
PORT=8000

# Production Redis (Upstash Pro)
REDIS_URL=redis://production-endpoint.upstash.io:6379

# Increase timeouts for production
ORCHESTRATOR_TIMEOUT=120000
TIMEOUT_WEATHER=15000
TIMEOUT_EVENTS=20000

# State retention
STATE_TTL=7200  # 2 hours
```

### Docker Compose Production

```yaml
# docker-compose.prod.yml
services:
  api:
    restart: always
    deploy:
      replicas: 3
      resources:
        limits:
          cpus: '1'
          memory: 1G
    
  weather-worker:
    restart: always
    deploy:
      replicas: 5
      resources:
        limits:
          cpus: '0.5'
          memory: 512M
```

**Deploy:**
```bash
docker-compose -f docker-compose.prod.yml up -d
```

### Load Balancing

**Nginx Configuration**:
```nginx
upstream ringmaster {
    least_conn;
    server api-1:8000;
    server api-2:8000;
    server api-3:8000;
}

server {
    listen 80;
    server_name yourdomain.com;

    location / {
        proxy_pass http://ringmaster;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }
}
```

### Monitoring

**Upstash Redis Metrics**:
- Commands per second
- Memory usage
- Connection count
- Latency

**Application Metrics**:
```bash
# Prometheus endpoint (if implemented)
GET /metrics

# Custom health endpoint
GET /health
```

---

## 📊 Performance Benchmarks

### Typical Response Times

| Endpoint | Sequential (v1) | Parallel (v2) | Improvement |
|----------|----------------|---------------|-------------|
| Complete Trip | 15-20s | 5-7s | **3x faster** |
| Weather Only | 2-3s | 2-3s | Same |
| Events Only | 3-4s | 3-4s | Same |
| With Streaming | N/A | Real-time | New feature |

### Throughput

- **Sequential**: ~3-4 requests/minute
- **Parallel**: ~10-12 requests/minute
- **With Scaling**: Up to 50+ requests/minute (5 replicas each)

---

## 🤝 Contributing

We welcome contributions! Here's how:

1. **Fork** the repository
2. **Create** a feature branch: `git checkout -b feature/amazing-feature`
3. **Make** your changes
4. **Test** thoroughly: `pytest tests/`
5. **Commit**: `git commit -m 'Add amazing feature'`
6. **Push**: `git push origin feature/amazing-feature`
7. **Open** a Pull Request

### Development Setup

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run tests
pytest

# Code formatting
black app/
isort app/

# Linting
flake8 app/
mypy app/
```

---

## 📄 License

MIT License - See [LICENSE](LICENSE) file for details

---

## 🙏 Acknowledgments

- **Redis/Upstash**: Pub/sub messaging infrastructure
- **FastAPI**: High-performance API framework
- **Google Gemini**: Advanced language model
- **OpenWeather**: Weather data provider
- **OpenRouteService**: Routing and navigation
- **OpenWeb Ninja**: Real-time events data

---

## 📧 Support & Contact

- **Issues**: [GitHub Issues](https://github.com/yourusername/ringmaster-round-table/issues)
- **Documentation**: http://localhost:8000/docs
- **Health Status**: http://localhost:8000/status

---

## 🗺️ Roadmap

### v2.1 (Planned)
- [ ] WebSocket support for bidirectional streaming
- [ ] Agent result caching
- [ ] Rate limiting per user
- [ ] Authentication & API keys

### v3.0 (Future)
- [ ] Machine learning for personalized recommendations
- [ ] Multi-destination itineraries
- [ ] Real-time price tracking
- [ ] Mobile app integration

---

**Happy Traveling!** ✈️🌍

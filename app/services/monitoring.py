import time
import psutil
from typing import Dict, Any
from prometheus_client import Counter, Histogram, Gauge, generate_latest
from fastapi import Response
import logging

logger = logging.getLogger(__name__)

# Prometheus metrics
REQUEST_COUNT = Counter(
    'llm_relay_requests_total',
    'Total number of requests',
    ['method', 'endpoint', 'status_code', 'api_key_name']
)

REQUEST_DURATION = Histogram(
    'llm_relay_request_duration_seconds',
    'Request duration in seconds',
    ['method', 'endpoint']
)

STREAMING_SESSIONS = Gauge(
    'llm_relay_streaming_sessions_active',
    'Number of active streaming sessions'
)

TOKEN_USAGE = Counter(
    'llm_relay_tokens_total',
    'Total tokens processed',
    ['type', 'model']  # type: prompt/completion
)

PROVIDER_REQUESTS = Counter(
    'llm_relay_provider_requests_total',
    'Requests to provider',
    ['provider_url', 'status_code']
)

SYSTEM_MEMORY = Gauge('llm_relay_memory_usage_bytes', 'Memory usage in bytes')
SYSTEM_CPU = Gauge('llm_relay_cpu_usage_percent', 'CPU usage percentage')

class MetricsCollector:
    """Collect and export metrics"""
    
    def __init__(self):
        self.active_streams = 0
    
    def record_request(
        self, 
        method: str, 
        endpoint: str, 
        status_code: int,
        duration: float,
        api_key_name: str = "unknown"
    ):
        """Record a request"""
        REQUEST_COUNT.labels(
            method=method,
            endpoint=endpoint, 
            status_code=status_code,
            api_key_name=api_key_name
        ).inc()
        
        REQUEST_DURATION.labels(
            method=method,
            endpoint=endpoint
        ).observe(duration)
    
    def record_provider_request(self, provider_url: str, status_code: int):
        """Record provider request"""
        PROVIDER_REQUESTS.labels(
            provider_url=provider_url,
            status_code=status_code
        ).inc()
    
    def record_token_usage(self, token_type: str, model: str, count: int):
        """Record token usage"""
        if count > 0:
            TOKEN_USAGE.labels(type=token_type, model=model).inc(count)
    
    def start_streaming_session(self):
        """Start streaming session"""
        self.active_streams += 1
        STREAMING_SESSIONS.set(self.active_streams)
    
    def end_streaming_session(self):
        """End streaming session"""
        self.active_streams = max(0, self.active_streams - 1)
        STREAMING_SESSIONS.set(self.active_streams)
    
    def update_system_metrics(self):
        """Update system metrics"""
        try:
            # Memory usage
            memory = psutil.virtual_memory()
            SYSTEM_MEMORY.set(memory.used)
            
            # CPU usage
            cpu_percent = psutil.cpu_percent()
            SYSTEM_CPU.set(cpu_percent)
        except Exception as e:
            logger.warning(f"Failed to collect system metrics: {e}")
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get health status"""
        try:
            memory = psutil.virtual_memory()
            cpu_percent = psutil.cpu_percent()
            
            status = {
                "status": "healthy",
                "timestamp": time.time(),
                "system": {
                    "memory_percent": memory.percent,
                    "memory_available": memory.available,
                    "cpu_percent": cpu_percent,
                    "active_streams": self.active_streams
                }
            }
            
            # Check for unhealthy conditions
            if memory.percent > 90:
                status["status"] = "degraded"
                status["warnings"] = status.get("warnings", [])
                status["warnings"].append("High memory usage")
            
            if cpu_percent > 90:
                status["status"] = "degraded"
                status["warnings"] = status.get("warnings", [])
                status["warnings"].append("High CPU usage")
            
            return status
            
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "status": "unhealthy",
                "timestamp": time.time(),
                "error": str(e)
            }

# Global metrics collector
metrics_collector = MetricsCollector()

def get_metrics_response() -> Response:
    """Generate Prometheus metrics response"""
    metrics_collector.update_system_metrics()
    return Response(
        content=generate_latest(),
        media_type="text/plain"
    )
import time
import asyncio
from typing import Dict, Optional
from collections import defaultdict, deque
from fastapi import HTTPException, status
from app.core.config import settings

class TokenBucket:
    """Token bucket for rate limiting"""
    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity
        self.tokens = capacity
        self.refill_rate = refill_rate
        self.last_refill = time.time()
        self.lock = asyncio.Lock()
    
    async def consume(self, tokens: int = 1) -> bool:
        """Try to consume tokens. Returns True if successful."""
        async with self.lock:
            now = time.time()
            # Refill tokens based on time elapsed
            elapsed = now - self.last_refill
            self.tokens = min(
                self.capacity,
                self.tokens + (elapsed * self.refill_rate)
            )
            self.last_refill = now
            
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

class RateLimiter:
    """Rate limiter service"""
    def __init__(self):
        self.buckets: Dict[str, TokenBucket] = {}
        self.cleanup_interval = 300  # 5 minutes
        self.last_cleanup = time.time()
    
    def _get_bucket_key(self, api_key_id: Optional[int], ip_address: str) -> str:
        """Generate bucket key for rate limiting"""
        if api_key_id:
            return f"api_key:{api_key_id}"
        return f"ip:{ip_address}"
    
    async def _cleanup_old_buckets(self):
        """Remove unused buckets to prevent memory leak"""
        now = time.time()
        if now - self.last_cleanup < self.cleanup_interval:
            return
        
        # Remove buckets that haven't been used in the last hour
        cutoff_time = now - 3600
        to_remove = []
        
        for key, bucket in self.buckets.items():
            if bucket.last_refill < cutoff_time:
                to_remove.append(key)
        
        for key in to_remove:
            del self.buckets[key]
        
        self.last_cleanup = now
    
    async def check_rate_limit(
        self, 
        api_key_id: Optional[int], 
        ip_address: str,
        tokens_requested: int = 1
    ) -> None:
        """Check rate limit and raise exception if exceeded"""
        
        await self._cleanup_old_buckets()
        
        bucket_key = self._get_bucket_key(api_key_id, ip_address)
        
        if bucket_key not in self.buckets:
            # Create new bucket
            rate_per_second = settings.rate_limit_per_minute / 60.0
            self.buckets[bucket_key] = TokenBucket(
                capacity=settings.rate_limit_per_minute,
                refill_rate=rate_per_second
            )
        
        bucket = self.buckets[bucket_key]
        
        if not await bucket.consume(tokens_requested):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": {
                        "message": "Rate limit exceeded",
                        "type": "rate_limit_error",
                        "code": "rate_limit_exceeded"
                    }
                },
                headers={"Retry-After": "60"}
            )

# Global rate limiter instance
rate_limiter = RateLimiter()

async def check_rate_limit(api_key_id: Optional[int], ip_address: str):
    """Global function to check rate limits"""
    await rate_limiter.check_rate_limit(api_key_id, ip_address)
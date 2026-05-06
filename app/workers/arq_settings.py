from arq.connections import RedisSettings

from app.config import get_settings


def get_redis_settings() -> RedisSettings:
    settings = get_settings()
    url = settings.redis_url
    # Parse redis://host:port/db
    if url.startswith("redis://"):
        url = url[8:]
    parts = url.split("/")
    host_port = parts[0]
    db = int(parts[1]) if len(parts) > 1 else 0

    if ":" in host_port:
        host, port_str = host_port.split(":")
        port = int(port_str)
    else:
        host = host_port
        port = 6379

    return RedisSettings(host=host, port=port, database=db)

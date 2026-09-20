from http.client import HTTPConnection

from src.core.config import Settings, get_settings


def healthcheck_host(settings: Settings) -> str:
    if not settings.allowed_hosts:
        raise ValueError("ALLOWED_HOSTS must not be empty for the health probe")
    host = settings.allowed_hosts[0]
    if host == "*":
        return "127.0.0.1"
    if host.startswith("*."):
        return f"healthcheck{host[1:]}"
    return host


def check_health(settings: Settings) -> None:
    host = healthcheck_host(settings)
    connection = HTTPConnection("127.0.0.1", 8000, timeout=3)
    try:
        connection.request("GET", "/healthz", headers={"Host": host})
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError(f"Health probe returned HTTP {response.status}")
    finally:
        connection.close()


if __name__ == "__main__":
    check_health(get_settings())

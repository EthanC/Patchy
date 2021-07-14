import json
from typing import Any, Dict, Optional

import httpx
from httpx import Response, codes
from loguru import logger


class Utility:
    """Utilitarian functions designed for Renovate."""

    def GET(self: Any, url: str) -> Optional[Dict[str, Any]]:
        """Perform an HTTP GET request and return its response."""

        res: Response = httpx.get(url)

        status: int = res.status_code
        data: str = res.text

        logger.debug(f"(HTTP {status}) GET {url}")
        logger.trace(data)

        if codes.is_error(status) is False:
            return json.loads(data)
        else:
            logger.error(f"(HTTP {status}) GET Failed {url}")
            logger.error(data)

    def POST(self: Any, url: str, payload: Dict[str, Any]) -> bool:
        """Perform an HTTP POST request and return its status."""

        res: Response = httpx.post(
            url, data=json.dumps(payload), headers={"content-type": "application/json"}
        )

        status: int = res.status_code
        data: str = res.text

        logger.debug(f"(HTTP {status}) POST {url}")
        logger.trace(data)

        if codes.is_error(status) is False:
            return True
        else:
            logger.error(f"(HTTP {status}) POST Failed {url}")
            logger.error(data)

            return False

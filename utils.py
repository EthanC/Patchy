import json
from typing import Any, Dict, Optional

import httpx
from httpx import Response, codes
from loguru import logger


class Utility:
    """Utilitarian functions designed for Renovate."""

    def GET(self: Any, url: str, raw: bool = False) -> Optional[Dict[str, Any]]:
        """Perform an HTTP GET request and return its response."""

        try:
            res: Response = httpx.get(url)
            data: str = res.text
        except Exception as e:
            logger.error(f"GET failed {url}, {e}")

            return

        status: int = res.status_code

        logger.debug(f"(HTTP {status}) GET {url}")
        logger.trace(data)

        if codes.is_error(status) is False:
            if raw is True:
                return data

            return json.loads(data)
        else:
            logger.error(f"(HTTP {status}) GET Failed {url}")
            logger.trace(data)

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

    def GetBattleBuild(
        self: Any, titleId: str, region: str, build: str
    ) -> Optional[str]:
        """Get the Build Name for the specified Battle.net title."""

        cdn: Optional[Dict[str, Any]] = Utility.GET(
            self, f"https://blizztrack.com/api/manifest/cdns/{titleId}"
        )

        if cdn is None:
            return

        path: Optional[str] = None
        host: Optional[str] = None

        for entry in cdn["data"]:
            if entry["region_name"].lower() != region.lower():
                continue

            path = entry["path"]
            host = entry["hosts"][0]

        if (path is None) or (host is None):
            return

        # https://github.com/BlizzTrack/BlizzTrack/blob/master/BlizzTrack/Pages/Partials/_view_versions.cshtml#L89
        dest: str = f"config/{build[:2]}/{build[2:4]}/{build}"
        buildConfig: Optional[Dict[str, Any]] = Utility.GET(
            self, f"http://{host}/{path}/{dest}", True
        )

        if buildConfig is None:
            return

        for line in str(buildConfig).splitlines():
            if line.startswith("build-name") is False:
                continue

            return line.split(" = ")[1]

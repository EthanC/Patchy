import json
from time import sleep
from typing import Any, Dict, Optional

import httpx
from httpx import HTTPError, Response, TimeoutException
from loguru import logger


class Utility:
    """Utilitarian functions designed for Renovate."""

    def GET(
        self: Any, url: str, raw: bool = False, isRetry: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Perform an HTTP GET request and return its response."""

        logger.debug(f"GET {url}")

        try:
            res: Response = httpx.get(url)
            status: int = res.status_code
            data: str = res.text

            res.raise_for_status()
        except HTTPError as e:
            if isRetry is False:
                logger.debug(f"(HTTP {status}) GET {url} failed, {e}... Retry in 10s")

                sleep(10)

                return Utility.GET(self, url, raw, True)

            logger.error(f"(HTTP {status}) GET {url} failed, {e}")

            return
        except TimeoutException as e:
            if isRetry is False:
                logger.debug(f"GET {url} failed, {e}... Retry in 10s")

                sleep(10)

                return Utility.GET(self, url, raw, True)

            # TimeoutException is common, no need to log as error
            logger.debug(f"GET {url} failed, {e}")

            return
        except Exception as e:
            if isRetry is False:
                logger.debug(f"GET {url} failed, {e}... Retry in 10s")

                sleep(10)

                return Utility.GET(self, url, raw, True)

            logger.error(f"GET {url} failed, {e}")

            return

        logger.trace(data)

        if raw is True:
            return data

        return json.loads(data)

    def POST(self: Any, url: str, payload: Dict[str, Any]) -> bool:
        """Perform an HTTP POST request and return its status."""

        try:
            res: Response = httpx.post(
                url,
                data=json.dumps(payload),
                headers={"content-type": "application/json"},
            )
            status: int = res.status_code
            data: str = res.text

            res.raise_for_status()
        except HTTPError as e:
            logger.error(f"(HTTP {status}) POST {url} failed, {e}")

            return False
        except TimeoutException as e:
            # TimeoutException is common, no need to log as error
            logger.debug(f"POST {url} failed, {e}")

            return False
        except Exception as e:
            logger.error(f"POST {url} failed, {e}")

            return False

        logger.trace(data)

        return True

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

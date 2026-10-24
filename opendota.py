"""Explicit, cached OpenDota reads with a persistent shared request budget."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ApiError(RuntimeError):
    pass


class Unavailable(ApiError):
    """A cached or new public-record absence; safe to skip during a batch."""
    pass


def transport(url):
    request = Request(url, headers={"User-Agent": "DotaBasedReplay/0.1 (local replay catalog)", "Accept": "application/json"})
    try:
        with urlopen(request, timeout=20) as response:
            body = response.read(8 * 1024 * 1024 + 1)
            if len(body) > 8 * 1024 * 1024:
                raise ApiError("OpenDota response exceeds size limit")
            return response.status, dict(response.headers), json.loads(body)
    except HTTPError as exc:
        return exc.code, dict(exc.headers), None
    except (URLError, OSError, ValueError) as exc:
        raise ApiError(f"OpenDota unavailable: {exc}") from exc


class OpenDota:
    def __init__(self, store, request=transport, now=time.time, sleep=time.sleep):
        self.store, self.request, self.now, self.sleep = store, request, now, sleep
        self.lock = threading.Lock()

    def fetch(self, endpoint):
        prefix, _, identifier = endpoint.partition("/")
        if prefix not in ("matches", "players") or not identifier.isdecimal():
            raise ValueError("Only numeric match/account lookups are supported")
        with self.lock:
            cached = self.store.cached(endpoint, now=self.now())
            if cached:
                if cached["status"] != 200:
                    raise Unavailable("No public OpenDota record; negative result cached for 24 hours")
                return cached["data"]
            now = self.now()
            day = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
            budget = self.store.get_pref("api_budget", {})
            if budget.get("day") != day:
                budget = {"day": day, "count": 0}
            if budget.get("count", 0) >= 1000:
                raise ApiError("Local daily budget of 1,000 OpenDota requests reached")
            delay = self.store.get_pref("api_next_at", 0) - now
            if delay > 5:
                raise ApiError(f"OpenDota cooling down; retry in {int(delay) + 1:,} seconds")
            if delay > 0:
                self.sleep(delay)
            budget["count"] = budget.get("count", 0) + 1
            self.store.set_pref("api_budget", budget)
            self.store.set_pref("api_next_at", self.now() + 2.1)
            status, headers, data = self.request("https://api.opendota.com/api/" + endpoint)
            headers = {key.lower(): value for key, value in headers.items()}
            if status == 429:
                value = headers.get("retry-after", "120")
                try:
                    delay = float(value)
                except ValueError:
                    try:
                        delay = parsedate_to_datetime(value).timestamp() - self.now()
                    except (ValueError, TypeError, OverflowError):
                        delay = 120
                self.store.set_pref("api_next_at", self.now() + max(120, delay))
                raise ApiError("OpenDota rate limited this IP; cooldown saved. Try later.")
            if headers.get("x-rate-limit-remaining-day") == "0":
                midnight = datetime.fromtimestamp(self.now(), timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp() + 86400
                self.store.set_pref("api_next_at", midnight)
            elif headers.get("x-rate-limit-remaining-minute") == "0":
                self.store.set_pref("api_next_at", self.now() + 65)
            if status in (400, 404):
                self.store.cache(endpoint, None, 86400, status, now=self.now())
                raise Unavailable("No public OpenDota record; negative result cached for 24 hours")
            if status != 200 or not isinstance(data, dict) or data.get("error"):
                self.store.set_pref("api_next_at", max(self.store.get_pref("api_next_at", 0), self.now() + 60))
                raise ApiError(f"OpenDota returned HTTP {status}; retry later")
            if prefix == "matches" and str(data.get("match_id")) != identifier:
                raise ApiError("OpenDota returned an unexpected match ID")
            self.store.cache(endpoint, data, 365 * 86400 if prefix == "matches" else 7 * 86400, now=self.now())
            return data

    def enrich(self, identifiers, cancelled=lambda: False, progress=lambda done, total, match_id: None):
        targets = list(identifiers)[:20]
        result = {"completed": 0, "unavailable": 0}
        for index, match_id in enumerate(targets):
            if cancelled():
                break
            progress(index, len(targets), match_id)
            try:
                self.fetch(f"matches/{match_id}")
                result["completed"] += 1
            except Unavailable:
                result["unavailable"] += 1
        return result

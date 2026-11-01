"""Mutable process-wide settings controlled by the administrator."""

from dataclasses import dataclass
import os
import threading


AGENT_STYLES = frozenset({"normal", "coach"})
WEATHERS = frozenset({"clear", "rain", "fog"})


@dataclass
class ServerSettings:
    agent_style: str = "normal"
    weather: str = "clear"


class ServerSettingsStore:
    def __init__(self) -> None:
        self._settings = ServerSettings()
        self._lock = threading.RLock()

    def get(self) -> dict[str, str]:
        with self._lock:
            return {
                "agentStyle": self._settings.agent_style,
                "weather": self._settings.weather,
            }

    def update(self, *, agent_style: str, weather: str) -> dict[str, str]:
        if agent_style not in AGENT_STYLES:
            raise ValueError(f"unsupported agent style: {agent_style}")
        if weather not in WEATHERS:
            raise ValueError(f"unsupported weather: {weather}")
        with self._lock:
            self._settings = ServerSettings(agent_style, weather)
        return self.get()

    def is_admin(self, username: str) -> bool:
        configured = os.getenv("ADMIN_USERNAME", "").strip()
        return bool(configured) and username == configured

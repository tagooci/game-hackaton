"""Mutable process-wide settings controlled by the administrator."""

from dataclasses import dataclass
import threading
import os


AGENT_STYLES = frozenset({"normal", "coach", "aggressive"})
WEATHERS = frozenset({"clear", "rain", "fog", "dark"})


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

    def update_weather(self, weather: str) -> dict[str, str]:
        if weather not in WEATHERS:
            raise ValueError(f"unsupported weather: {weather}")
        with self._lock:
            self._settings = ServerSettings(self._settings.agent_style, weather)
        return self.get()

    def is_admin(self, player_id: str) -> bool:
        admin_id = os.getenv("GAME_ADMIN_PLAYER_ID", "").strip()
        return bool(admin_id) and player_id == admin_id

import os
import unittest
from unittest.mock import patch

from server.server_settings import ServerSettingsStore


class AdminSecurityTests(unittest.TestCase):
    def test_admin_disabled_without_configuration(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = ServerSettingsStore()
            self.assertFalse(settings.is_admin('p1'))
            self.assertFalse(settings.is_admin(''))

    def test_only_explicit_existing_player_id_can_be_admin(self):
        with patch.dict(os.environ, {'GAME_ADMIN_PLAYER_ID': 'p7'}):
            settings = ServerSettingsStore()
            self.assertTrue(settings.is_admin('p7'))
            self.assertFalse(settings.is_admin('p1'))
            self.assertFalse(settings.is_admin('admin@example.invalid'))

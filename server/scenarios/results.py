"""Idempotent SQLite results. The host calls save once a scenario finishes."""
import json
import sqlite3


class ResultStore:
    def __init__(self, path):
        self.connection = sqlite3.connect(path)
        self.connection.execute('''CREATE TABLE IF NOT EXISTS scenario_results (
            result_id TEXT PRIMARY KEY, scene_id TEXT NOT NULL,
            result_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )''')
        self.connection.commit()

    def save(self, result):
        with self.connection:
            cursor = self.connection.execute(
                'INSERT OR IGNORE INTO scenario_results(result_id, scene_id, result_json) VALUES (?, ?, ?)',
                (result['resultId'], result['sceneId'], json.dumps(result, ensure_ascii=False)))
        return cursor.rowcount == 1

    def get(self, result_id):
        row = self.connection.execute(
            'SELECT result_json FROM scenario_results WHERE result_id = ?', (result_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def close(self):
        self.connection.close()

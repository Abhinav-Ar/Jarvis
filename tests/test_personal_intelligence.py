import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from personal_intelligence import APPLE_EPOCH, PersonalIntelligence, infer_recall_request


class PersonalIntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.messages = root / "chat.db"
        with sqlite3.connect(self.messages) as db:
            db.executescript("""
                CREATE TABLE message (
                    ROWID INTEGER PRIMARY KEY, guid TEXT, text TEXT, attributedBody BLOB,
                    date INTEGER, is_from_me INTEGER, handle_id INTEGER
                );
                CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT);
                CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, chat_identifier TEXT, display_name TEXT);
                CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER);
            """)
            db.execute("INSERT INTO handle VALUES(1,'+1 (555) 123-4567')")
            db.execute("INSERT INTO chat VALUES(1,'+15551234567','')")
            apple_date = int((time.time() - APPLE_EPOCH) * 1_000_000_000)
            db.execute(
                "INSERT INTO message VALUES(1,'message-1',?,NULL,?,0,1)",
                ("I can pick you up at 7:30 tonight", apple_date),
            )
            db.execute("INSERT INTO chat_message_join VALUES(1,1)")
        self.intelligence = PersonalIntelligence(root / "agent.db", self.messages)
        self.intelligence.remember_person(
            "Alex Rivera", aliases=["Alex"], identities=[("phone", "+1 555 123 4567")],
        )

    def tearDown(self):
        self.directory.cleanup()

    def test_indexes_and_recalls_message_by_person_and_subject(self):
        result = self.intelligence.recall("pick you up", person="Alex", sources=["messages"])
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["matches"]), 1)
        self.assertEqual(result["matches"][0]["sender"], "Alex Rivera")
        self.assertIn("7:30", result["matches"][0]["content"])

    def test_connector_status_explains_discord_authorization(self):
        statuses = {item["source"]: item for item in self.intelligence.connector_status()["connectors"]}
        self.assertEqual(statuses["discord"]["status"], "authorization_required")
        self.assertIn("local", self.intelligence.connector_status()["privacy"].lower())

    def test_recall_language_extracts_person_and_subject(self):
        result = infer_recall_request("When did Alex say he was going to pick me up?")
        self.assertEqual(result["person"], "Alex")
        self.assertEqual(result["query"], "pick me up")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.context_provenance import SYSTEM_POLICY, TRUSTED_KNOWLEDGE, USER_INPUT, label
from core.evaluation import get_evaluation, record_evaluation, update_evaluation
from core.memory_engine import approve_memory_candidate, create_memory_candidate, search_memory, supersede_memory
from core.memory_governance import MemoryCandidate, validate_candidate
from core.request_context import RequestContext, new_request_id
from services.knowledge_sync import ApprovedSource, KnowledgeCandidate, KnowledgeSync


class IntelligenceFoundationTests(unittest.TestCase):
    def test_request_id_and_channel_boundary_exist(self):
        context = RequestContext.portfolio("session")
        self.assertTrue(context.request_id.startswith("req-"))
        self.assertTrue(new_request_id().startswith("req-"))

    def test_context_provenance_is_explicit(self):
        self.assertEqual(label(SYSTEM_POLICY, "policy"), "[SYSTEM_POLICY]\npolicy")
        self.assertEqual(label(TRUSTED_KNOWLEDGE, "source"), "[TRUSTED_KNOWLEDGE]\nsource")
        self.assertEqual(label(USER_INPUT, "hello"), "[USER_INPUT]\nhello")

    def test_evaluation_lifecycle_is_durable(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/"memory.db"
            self.assertTrue(record_evaluation(request_id="req-test",channel="telegram",response="answer",db_path=db))
            self.assertTrue(update_evaluation("req-test",status="needs_review",feedback="incorrect",correction_candidate="correct",db_path=db))
            row=get_evaluation("req-test",db)
            self.assertEqual(row["status"],"needs_review")
            self.assertEqual(row["approval_status"],"pending")

    def test_memory_candidate_requires_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            import core.memory_engine as engine
            old=engine.DB
            engine.DB=Path(tmp)/"memory.db"
            try:
                candidate=create_memory_candidate(user_id="u1",category="stable_preference",content="prefers concise answers")
                self.assertIsNotNone(candidate)
                self.assertEqual(search_memory("concise",user_id="u1"),[])
                self.assertTrue(approve_memory_candidate(candidate))
                self.assertEqual(len(search_memory("concise",user_id="u1")),1)
                self.assertTrue(supersede_memory(1))
                self.assertEqual(search_memory("concise",user_id="u1"),[])
            finally:
                engine.DB=old

    def test_memory_candidate_validation(self):
        self.assertTrue(validate_candidate(MemoryCandidate("u1","fact","user_fact"))[0])
        self.assertFalse(validate_candidate(MemoryCandidate("","fact","user_fact"))[0])

    def test_knowledge_candidate_validation(self):
        sync=KnowledgeSync([ApprovedSource("github","public/repo","README.md","OMNIX")])
        with self.assertRaises(PermissionError):
            sync.sync("public/repo","other.md","content","sha")
        with self.assertRaises(ValueError):
            sync._validate_candidate(KnowledgeCandidate("public/repo","README.md","OMNIX","", "sha"))

if __name__=="__main__":
    unittest.main()

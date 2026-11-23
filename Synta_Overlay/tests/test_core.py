"""Run from the codelume folder:  python -m unittest discover -s tests -v

Covers everything that does not need Windows, Tkinter or a real OpenAI key.
"""
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import checker
import config
import diagnostic
import learner
import session
import tutor

LOOP_NO_COLON = "for n in [10, 20, 30]\n    print(n)\n"
LOOP_FIXED = "for n in [10, 20, 30]:\n    print(n)\n"
TYPES_BUG = 'score = "75"\nif score >= 50:\n    print("Passed")\n'


class CheckerTests(unittest.TestCase):
    def test_acceptance_1_missing_colon_then_fixed(self):
        r = checker.check_python(LOOP_NO_COLON)
        self.assertFalse(r.ok)
        self.assertEqual(r.line, 1)
        self.assertEqual(r.kind, "missing_colon")
        self.assertIn("colon", r.explanation)
        r2 = checker.check_python(LOOP_FIXED)         # second check reflects the edit
        self.assertTrue(r2.ok)

    def test_windows_line_endings(self):
        r = checker.check_python(LOOP_NO_COLON.replace("\n", "\r\n"))
        self.assertEqual((r.ok, r.line), (False, 1))

    def test_acceptance_2_types_bug_passes_syntax(self):
        self.assertTrue(checker.check_python(TYPES_BUG).ok)

    def test_empty(self):
        self.assertTrue(checker.check_python("  \n\n").empty)

    def test_not_executed(self):
        marker = os.path.join(tempfile.gettempdir(), "codelume_exec_marker")
        if os.path.exists(marker):
            os.remove(marker)
        code = f"open({marker!r}, 'w').write('x')\n"
        self.assertTrue(checker.check_python(code).ok)
        self.assertFalse(os.path.exists(marker), "checking must never run the code")

    def test_other_errors(self):
        cases = {
            "print('hi'\n": "bracket_open",
            "def f():\nprint(1)\n": "indent_missing",
            "x = 1\n    y = 2\n": "indent_unexpected",
            "s = 'abc\n": "string_open",
            "print 'hi'\n": "print_call",
            "x = 5\nif x = 5:\n    pass\n": "assign_in_condition",
            "x = )\n": "bracket_extra",
        }
        for src, kind in cases.items():
            r = checker.check_python(src)
            self.assertFalse(r.ok, src)
            self.assertEqual(r.kind, kind, f"{src!r} -> {r.kind} / {r.raw_message}")

    def test_level_text(self):
        r = checker.check_python(LOOP_NO_COLON)
        self.assertIn("header", checker.describe(r, "beginner")[1].lower())
        self.assertIn("Python's own message", checker.describe(r, "intermediate")[1])
        self.assertLess(len(checker.describe(r, "advanced")[1]), len(checker.describe(r, "beginner")[1]))
        ok = checker.describe(checker.check_python(TYPES_BUG), "beginner")[1]
        self.assertIn("did not run it", ok)

    def test_signature_ignores_line_number(self):
        a = checker.signature(checker.check_python(LOOP_NO_COLON))
        b = checker.signature(checker.check_python("# x\n" + LOOP_NO_COLON))
        self.assertEqual(a, b)


class SessionTests(unittest.TestCase):
    def test_ladder_and_repeat(self):
        s = session.HelpSession()
        self.assertEqual(s.stage, "nudge")
        s.record("nudge", "code", "look at line 1")
        self.assertTrue(s.is_repeat("code", "nudge"))
        self.assertFalse(s.is_repeat("code changed", "nudge"))
        self.assertTrue(s.escalate() and s.escalate() and s.escalate())
        self.assertEqual(s.stage, "solution")
        self.assertFalse(s.escalate())

    def test_reset_when_problem_changes(self):
        s = session.HelpSession()
        self.assertIsNone(s.note_signature("missing_colon:x"))
        s.escalate()
        s.record("hint", "c", "t")
        self.assertIsNone(s.note_signature("missing_colon:x"))
        self.assertEqual(s.stage, "hint")               # same problem: stays
        self.assertEqual(s.note_signature("ok"), "missing_colon:x")
        self.assertEqual((s.stage, s.records), ("nudge", []))


class LearnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "profile.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_consent_no_file(self):
        p = learner.LearnerProfile(self.path)
        p.set_consent(False)
        p.log_attempt("debugging")
        self.assertFalse(self.path.exists())

    def test_consent_saves_and_forget_deletes(self):
        p = learner.LearnerProfile(self.path)
        p.set_consent(True)
        p.set_level("intermediate")
        p.log_attempt("debugging")
        again = learner.LearnerProfile.load(self.path)
        self.assertEqual((again.level, again.consent), ("intermediate", True))
        self.assertEqual(again.topics["debugging"]["attempts"], 1)
        text = self.path.read_text()
        self.assertNotIn("print(", text)
        p.forget()
        self.assertFalse(self.path.exists())

    def test_path_skips_strong_topics(self):
        p = learner.LearnerProfile(self.path)
        p.apply_diagnostic({
            "control_flow": (5, 5),             # loops understood
            "syntax_types": (0, 5),             # types are weak
            "functions_scope": (3, 5),
            "data_structures": (5, 5),
            "debugging": (4, 5),
            "problem_solving": (5, 5)})
        topics = [i.topic for i in p.path_items()]
        self.assertEqual(topics[0], "syntax_types")
        self.assertNotIn("control_flow", topics)
        self.assertIn("Do not re-teach".lower(), ("do not re-teach " + p.prompt_summary()).lower())
        self.assertIn("Control flow", p.prompt_summary().split("needs work")[0])
        self.assertEqual(p.recommended_level(), "intermediate")

    def test_success_credit_scales_with_help(self):
        p = learner.LearnerProfile(self.path)
        p.log_attempt("debugging")
        p.log_success("debugging", "nudge")
        high = p.mastery("debugging")
        q = learner.LearnerProfile(self.path)
        q.log_attempt("debugging")
        q.log_success("debugging", "solution")
        self.assertGreater(high, q.mastery("debugging"))


class DiagnosticTests(unittest.TestCase):
    def test_sizes_and_balance(self):
        for n, expect in ((25, 25), (20, 20), (30, 30), (5, 20), (99, 30)):
            qs = diagnostic.select_questions(n, seed=1)
            self.assertEqual(len(qs), expect)
            for t in learner.TOPICS:
                self.assertGreaterEqual(sum(q.topic == t for q in qs), expect // 6)

    def test_bank_is_well_formed(self):
        self.assertEqual(len(diagnostic.BANK), 30)
        for q in diagnostic.BANK:
            self.assertIn(q.topic, learner.TOPICS)
            self.assertIn(q.kind, ("predict", "fix", "explain", "approach"))
            self.assertTrue(0 <= q.answer < len(q.options))
            self.assertEqual(len(set(q.options)), len(q.options))

    def test_predict_answers_are_really_correct(self):
        """Executes the bank's own snippets (in a subprocess) to prove the keyed answers."""
        checked = 0
        for q in diagnostic.BANK:
            if q.kind == "predict":
                out = subprocess.run([sys.executable, "-c", q.code], capture_output=True, text=True, timeout=10)
                self.assertEqual(out.returncode, 0, q.code)
                self.assertEqual(out.stdout.strip(), q.options[q.answer], q.code)
                checked += 1
        self.assertGreaterEqual(checked, 15)

    def test_crash_snippets_really_fail(self):
        """Questions that say the code crashes/raises must really fail when run."""
        checked = 0
        for q in diagnostic.BANK:
            if q.code and any(w in q.prompt for w in ("crash", "raises", "SyntaxError", "gives a SyntaxError")):
                out = subprocess.run([sys.executable, "-c", q.code], capture_output=True, text=True,
                                     timeout=10, input="x\n")
                self.assertNotEqual(out.returncode, 0, q.code)
                checked += 1
        self.assertGreaterEqual(checked, 4)

    def test_run_scoring_and_profile(self):
        run = diagnostic.DiagnosticRun(25, seed=3)
        self.assertEqual(run.total, 25)
        for i, item in enumerate(run.items):
            run.answer(item.answer if i % 2 == 0 else (item.answer + 1) % len(item.options))
        self.assertTrue(run.done)
        summary = run.summary()
        self.assertEqual(sum(n for _, n in summary.values()), 25)
        self.assertEqual(sum(c for c, _ in summary.values()), 13)


class FakeAPI(http.server.BaseHTTPRequestHandler):
    mode = "ok"
    last_request = None

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeAPI.last_request = (self.headers.get("Authorization"), body)
        m = FakeAPI.mode
        if self.path != "/api/chat":
            code, payload = 404, {}
        elif m == "ok":
            code, payload = 200, {"message": {"content": "Look at the loop header.\nTOPIC: syntax_types"}}
        elif m == "empty":
            code, payload = 200, {"message": {"content": ""}}
        elif m == "malformed":
            code, payload = 200, {}
        elif m == "model":
            code, payload = 404, {"error": "model missing"}
        else:
            code, payload = 500, {"error": "model failed"}
        raw = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class TutorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), FakeAPI)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def ask(self, mode="ok", **kw):
        FakeAPI.mode = mode
        check = checker.check_python(LOOP_NO_COLON)
        args = dict(code=LOOP_NO_COLON, check=check, level="beginner", stage="nudge",
                    port=self.server.server_port, timeout=5)
        args.update(kw)
        return tutor.ask_tutor(**args)

    def test_success_and_request_shape(self):
        r = self.ask("ok")
        self.assertTrue(r.ok)
        self.assertEqual(r.topic, "syntax_types")
        self.assertNotIn("TOPIC:", r.text)
        auth, body = FakeAPI.last_request
        self.assertIsNone(auth)
        self.assertFalse(body["stream"])
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user"])
        self.assertIn("  1 | for n in [10, 20, 30]", body["messages"][1]["content"])
        self.assertIn("CONFIRMED by Python's parser", body["messages"][1]["content"])
        self.assertIn("NOT run", body["messages"][0]["content"])
        self.assertIn("STEP: NUDGE", body["messages"][0]["content"])
        self.assertIn("first program", body["messages"][0]["content"])

    def test_syntax_ok_prompt_marks_inference(self):
        r = self.ask("ok", code=TYPES_BUG, check=checker.check_python(TYPES_BUG), level="advanced", stage="hint")
        self.assertTrue(r.ok)
        _, body = FakeAPI.last_request
        self.assertIn("NO syntax error", body["messages"][1]["content"])
        self.assertIn("inferred, not run", body["messages"][0]["content"])
        self.assertIn("STEP: HINT", body["messages"][0]["content"])
        self.assertIn("LEVEL: advanced", body["messages"][0]["content"])

    def test_history_expected_and_profile_in_prompt(self):
        r = self.ask("ok", learner_summary="strong (do not re-teach): Control flow; needs work: Syntax and types",
                     hints_so_far=["[Nudge] check line 1"], expected="print each number")
        self.assertTrue(r.ok)
        text = FakeAPI.last_request[1]["messages"][1]["content"]
        for s in ("SKILL PROFILE", "do not re-teach", "HINTS ALREADY GIVEN", "print each number"):
            self.assertIn(s, text)

    def test_type_nudge_grounds_line_without_revealing_fix(self):
        r = self.ask(code=TYPES_BUG, check=checker.check_python(TYPES_BUG))
        self.assertIn("line 2", r.text)
        self.assertNotIn("int(", r.text)
        self.assertIsNone(tutor.comparison_clue('x = "75"\nx = 75\nif x >= 50: pass'))

    def test_model_missing(self):
        self.assertIn("ollama pull", self.ask("model").error_detail)

    def test_server_failure(self):
        self.assertEqual(self.ask("boom").kind, "server")

    def test_empty_response(self):
        self.assertEqual(self.ask("empty").kind, "empty")

    def test_malformed_response(self):
        self.assertEqual(self.ask("malformed").kind, "api")

    def test_connection_failure(self):
        self.assertEqual(self.ask(port=1).kind, "network")

    def test_helpers(self):
        self.assertEqual(tutor.extract_code_block("x\n```python\nprint(1)\n```\ny"), "print(1)\n")
        self.assertEqual(tutor.split_topic("hi\nTOPIC: nonsense"), ("hi", None))
        long_code = "x = 1\n" * 5000
        built = tutor.build_input(long_code, checker.check_python("x=1"))
        self.assertIn("was cut", built)


if __name__ == "__main__":
    unittest.main()

"""Test không gọi model: `python -m unittest discover -s ai-system/pdc-onboarding-eval/tool/tests`."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOL))

from obeval import compare, dashboard, pipeline, prompt, report, score, transcript, validate, verify  # noqa: E402
from obeval import ensemble as ensemble_mod  # noqa: E402

CRIT = prompt.load_criteria()
SCHEMA = prompt.load_schema()
NAMES = report.Names(CRIT)

SEGS = [
    (3, "SPEAKER_00", "Thầy xin chào gia đình mình, hai mẹ con nghe rõ tiếng thầy chưa ạ?"),
    (10, "SPEAKER_01", "Dạ nghe rõ ạ."),
    (20, "SPEAKER_00", "Thầy tên là Khang, thầy đã đồng hành cùng nhiều bạn tuổi teen."),
    (600, "SPEAKER_00", "Con khỏe không?"),
    (605, "SPEAKER_01", "Dạ con khỏe."),
    (610, "SPEAKER_00", "Rồi mình qua phần sở thích nhé, chắc con thích chơi game đúng không."),
    (2500, "SPEAKER_00", "Ưu đãi này chỉ trong 24 giờ, mẹ quyết luôn hôm nay giúp thầy nhé."),
    (2520, "SPEAKER_01", "Để chị bàn với ba cháu đã."),
]


def make_tr():
    segs = [transcript.Segment(float(t), float(t) + 5, s, x) for t, s, x in SEGS]
    return transcript.finalize(segs, "test")


def ev(ts, spk, q):
    return {"timestamp": ts, "speaker": spk, "quote": q}


def fake_raw(overrides=None):
    crit = []
    for c in CRIT["criteria"]:
        crit.append({"id": c["id"], "status": "NA", "rationale": "không phát sinh", "evidence": [], "missing_elements": []})
    by = {c["id"]: c for c in crit}
    by["OB01"].update(status="FF", evidence=[ev("00:00:03", "Mentor", "hai mẹ con nghe rõ tiếng thầy chưa ạ")])
    by["OB02"].update(status="FF", evidence=[ev("00:00:20", "Mentor", "Thầy tên là Khang")])
    by["OB08"].update(status="NF", evidence=[ev("00:10:00", "Mentor", "Con khỏe không?")])
    by["OB09"].update(status="PF", evidence=[ev("00:10:10", "Mentor", "chắc con thích chơi game đúng không")])
    by["OB36"].update(status="NF", evidence=[ev("00:41:40", "Mentor", "câu này không hề có trong buổi học")])
    raw = {
        "data_quality": {"transcript_coverage": "partial", "speaker_confidence": "medium",
                         "speaker_mapping": [{"label": "SPEAKER_00", "role": "mentor"}], "issues": [], "insufficient_data": False},
        "activities_timeline": [{"activity": 1, "found": True, "start": "00:00:03", "end": "00:05:00"}],
        "sequence": {"status": "LECH_NHE", "observed_activity_order": [1, 3, 5], "deviations": []},
        "criteria": crit,
        "links": [{"id": f"LK0{i}", "status": "KHONG_DU_DU_LIEU", "rationale": "", "evidence": []} for i in range(1, 7)],
        "flags": [
            {"id": "F09", "severity": "high", "explanation": "tạo khẩn cấp", "script_instructed": True,
             "evidence": [ev("00:41:40", "Mentor", "Ưu đãi này chỉ trong 24 giờ, mẹ quyết luôn hôm nay")]},
            {"id": "F01", "severity": "low", "explanation": "bịa", "script_instructed": False,
             "evidence": [ev("00:01:00", "Mentor", "một câu bịa hoàn toàn khác")]},
        ],
        "strengths": [{"criterion_id": "OB01", "step_name": "Chào hỏi", "description": "Kiểm tra âm thanh",
                       "evidence": [ev("00:00:03", "Mentor", "nghe rõ tiếng thầy chưa ạ")]}],
        "improvements": [{"criterion_id": "OB08", "step_name": "Check-in", "evidence": [ev("00:10:00", "Mentor", "Con khỏe không?")],
                          "problem": "Chỉ hỏi khỏe không", "logic_impact": "Mất dữ liệu cảm xúc", "suggestion": "Hỏi thang 1–10",
                          "suggested_script": "Hôm nay con thấy mình ở mức mấy?", "priority": "high"}],
        "summary_for_mentor": "Thầy chào hỏi tốt.",
    }
    if overrides:
        raw.update(overrides)
    return raw


class TestTranscript(unittest.TestCase):
    def test_parse_time(self):
        self.assertEqual(transcript.parse_time("01:02:03"), 3723.0)
        self.assertEqual(transcript.parse_time("02:03"), 123.0)
        self.assertIsNone(transcript.parse_time(-1))
        self.assertIsNone(transcript.parse_time("-1"))
        self.assertEqual(transcript.parse_time(12.5), 12.5)

    def test_mask_phone_keeps_price(self):
        txt, n = transcript.mask_numbers("Zalo 0912 345 678, học phí 12.000.000 đồng, 1.000.000.000, TK 19034567890123")
        self.assertEqual(n, 2)
        self.assertIn("12.000.000", txt)
        self.assertIn("1.000.000.000", txt)
        self.assertNotIn("0912", txt)

    def test_cyrillic_homoglyph(self):
        self.assertEqual(transcript.clean_text("cоn"), "con")  # 'о' Cyrillic

    def _load(self, content, suffix):
        with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8") as f:
            f.write(content)
        return transcript.load(f.name)

    def test_stt_json(self):
        tr = self._load(json.dumps({"segments": [{"start": 1.0, "end": 2.0, "speaker": "SPEAKER_00", "text": "Chào"}]}), ".json")
        self.assertEqual(tr.source_format, "json_segments")
        self.assertEqual(tr.segments[0].speaker, "SPEAKER_00")

    def test_db_row_minus_one(self):
        row = {"id": "x", "transcript": [{"text": "Chào con", "start_time": -1, "end_time": -1, "word_count": 2}]}
        tr = self._load(json.dumps(row), ".json")
        self.assertEqual(tr.source_format, "db_row")
        self.assertFalse(tr.has_timestamps)
        self.assertIn("[#0001] ?: Chào con", transcript.render(tr))

    def test_ms_keys(self):
        tr = self._load(json.dumps({"utterances": [{"start_ms": 61000, "end_ms": 62000, "speaker": "A", "text": "x"}]}), ".json")
        self.assertEqual(tr.segments[0].start, 61.0)

    def test_meet_text(self):
        tr = self._load("Cuộc họp - Transcript\n00:00:00\n\nThầy Khang: Chào cả nhà\nMẹ Thu: Dạ chào thầy\n00:05:00\nThầy Khang: Mình bắt đầu nhé\n", ".txt")
        self.assertEqual(tr.source_format, "meet_text")
        self.assertEqual(len(tr.segments), 3)
        self.assertEqual(tr.segments[2].start, 300.0)

    def test_bracket_text(self):
        tr = self._load("[00:01:02] Mentor: Xin chào\n[00:01:05] PH: Dạ\n", ".txt")
        self.assertEqual(tr.source_format, "timed_text")
        self.assertEqual(tr.segments[1].speaker, "PH")

    def test_srt(self):
        tr = self._load("1\n00:00:01,000 --> 00:00:03,000\nMentor: Xin chào\n\n2\n00:00:04,000 --> 00:00:05,000\nDạ\n", ".srt")
        self.assertEqual(tr.source_format, "srt_vtt")
        self.assertEqual(tr.segments[0].speaker, "Mentor")


class TestPrompt(unittest.TestCase):
    def test_schema_for_api(self):
        s = json.dumps(prompt.schema_for_api(SCHEMA))
        for bad in ("$ref", "$defs", "$comment", "pattern", "minItems", "maxItems"):  # 37 phần tử → Vertex "too many states"
            self.assertNotIn(bad, s)
        # trường tên "description" là dữ liệu, không phải từ khoá — phải giữ (Vertex 400 ngày 09/10)
        dev = prompt.schema_for_api(SCHEMA)["properties"]["sequence"]["properties"]["deviations"]["items"]
        self.assertIn("description", dev["properties"])
        self.assertIn("description", dev["required"])
        self.assertIn("timestamp", dev["properties"]["evidence"]["items"]["properties"])

    def test_system_prompt_strips_comment(self):
        self.assertNotIn("<!--", prompt.load_system_prompt())


class TestPostprocess(unittest.TestCase):
    def setUp(self):
        self.tr = make_tr()

    def test_normalize_fills_missing(self):
        raw = fake_raw()
        raw["criteria"] = raw["criteria"][:30] + [dict(raw["criteria"][0])]
        res, issues = validate.normalize(raw)
        self.assertEqual([c["id"] for c in res["criteria"]], validate.OB_IDS)
        self.assertEqual(res["criteria"][36]["status"], "NE")
        self.assertTrue(any("2 lần" in i for i in issues))

    def test_verify_downgrades_fabricated(self):
        res, _ = validate.normalize(fake_raw())
        res, issues, stats = verify.verify(res, self.tr)
        by = {c["id"]: c for c in res["criteria"]}
        self.assertEqual(by["OB36"]["status"], "NE")           # trích dẫn bịa → NE
        self.assertEqual(by["OB36"]["status_model"], "NF")
        self.assertEqual(by["OB08"]["status"], "NF")           # trích dẫn thật → giữ
        self.assertEqual([f["id"] for f in res["flags"]], ["F09"])  # cờ bịa bị tách ra
        self.assertEqual([f["id"] for f in res["flags_unverified"]], ["F01"])
        self.assertGreater(stats["not_found"], 0)

    def test_verify_corrects_timestamp(self):
        res, _ = validate.normalize(fake_raw())
        res, _, _ = verify.verify(res, self.tr)
        f09 = res["flags"][0]["evidence"][0]
        self.assertEqual(f09["timestamp"], "00:41:40")         # model ghi 00:41:40, thật 2500s = 00:41:40
        ob08 = {c["id"]: c for c in res["criteria"]}["OB08"]["evidence"][0]
        self.assertEqual(ob08["timestamp"], "00:10:00")

    def test_verify_wrong_timestamp_fixed(self):
        res, _ = validate.normalize(fake_raw())
        res["criteria"][1]["evidence"] = [ev("00:30:00", "Mentor", "Thầy tên là Khang")]
        res, _, _ = verify.verify(res, self.tr)
        e2 = res["criteria"][1]["evidence"][0]
        self.assertTrue(e2["timestamp_corrected"])
        self.assertEqual(e2["timestamp"], "00:00:20")

    def test_fuzzy_and_ellipsis(self):
        qi = verify.QuoteIndex(self.tr)
        self.assertEqual(qi.locate("Thầy xin chào gia đình mình ... nghe rõ tiếng thầy")[0], "exact")
        self.assertEqual(qi.locate("Thầy tên là Khang, thầy đã đồng hành cùng nhiều bạn tuổi teen nha")[0], "fuzzy")
        self.assertEqual(qi.locate("hoàn toàn không liên quan gì cả")[0], "not_found")
        # ca thật 09/10: model đổi 1 chữ trong phần sau dấu "…" ("bình yên" → "bình an")
        tr2 = transcript.finalize([transcript.Segment(5.0, 9.0, "S0", (
            "Thân cường là cơ thể khỏe, có sức để ngồi vẽ hàng giờ. Trí sáng là kiến thức và tư duy, "
            "giúp con học Toán tốt hơn và hiểu hình khối. Tâm an là tâm hồn bình yên, giúp con bớt run khi đưa tranh."))], "t")
        q2 = verify.QuoteIndex(tr2)
        self.assertEqual(q2.locate("Trí sáng là kiến thức và tư duy, giúp con học Toán tốt hơn... "
                                   "Tâm an là tâm hồn bình an, giúp con bớt run")[0], "fuzzy")
        self.assertEqual(q2.locate("Tâm an là tâm hồn bình yên... Trí sáng là kiến thức và tư duy")[0], "not_found")  # sai thứ tự
        self.assertEqual(q2.locate("con bớt run khi đưa")[0], "exact")
        self.assertEqual(q2.locate("con bớt sợ khi")[0], "not_found")  # ngắn → phải nguyên văn

    def test_score(self):
        res, _ = validate.normalize(fake_raw())
        res, _, _ = verify.verify(res, self.tr)
        sc = score.compute(res, CRIT)
        a1 = next(a for a in sc["activities"] if a["activity"] == 1)
        self.assertEqual(a1["score"], 1.0)                      # OB01, OB02 FF; còn lại NA
        a3 = next(a for a in sc["activities"] if a["activity"] == 3)
        self.assertEqual(a3["score"], 0.25)                     # OB08 NF + OB09 PF
        self.assertAlmostEqual(sc["overall"], (10 * 1.0 + 35 * 0.25) / 45)
        self.assertEqual(sc["classification"], "CHECH_KICH_BAN")

    def test_insufficient_when_many_ne(self):
        raw = fake_raw()
        for c in raw["criteria"]:
            c["status"] = "NE"
        res, _ = validate.normalize(raw)
        sc = score.compute(res, CRIT)
        self.assertEqual(sc["classification"], "THIEU_DU_LIEU")
        self.assertIsNone(sc["overall"])


class TestReports(unittest.TestCase):
    def setUp(self):
        res, _ = validate.normalize(fake_raw())
        self.res, _, _ = verify.verify(res, make_tr())
        self.sc = score.compute(self.res, CRIT)
        self.meta = {"session_date": "2026-10-09", "mentor_name": "Thầy Khang", "mentor_email": "khang@example.com", "case_id": "t1"}

    def test_email_uses_step_names(self):
        h = report.mentor_email_html(self.res, self.sc, self.meta, NAMES)
        self.assertIn("Xác nhận không gian riêng tư và cảm xúc của con", h)  # tên OB08, không chỉ mã
        self.assertIn("Chào Thầy Khang", h)
        self.assertIn("đang xem lại cách đánh giá", h)                     # cờ theo kịch bản
        self.assertNotIn("một câu bịa", h)                                 # cờ bịa không vào email
        eml = report.mentor_eml(self.res, self.sc, self.meta, NAMES)
        self.assertIn(b"X-Unsent: 1", eml)

    def test_email_replaces_codes_with_step_names(self):
        self.res["improvements"][0]["suggestion"] = "Sau khi nhắc triết lý (OB28), hỏi kỹ OB29 rồi mới nói giá; tránh F09."
        h = report.mentor_email_html(self.res, self.sc, self.meta, NAMES)
        self.assertNotIn("OB28", h)
        self.assertNotIn("OB29", h)
        self.assertIn("Nhắc lại nội dung buổi khai giảng", h)
        self.assertIn("Khai thác lý do gia đình lựa chọn TeenCare", h)

    def test_dashboard_has_no_names(self):
        row = dashboard.make_row("t1", self.meta, self.res, self.sc, "done", NAMES)
        blob = json.dumps(row, ensure_ascii=False)
        for secret in ("Khang", "khang@example.com", "Con khỏe không"):
            self.assertNotIn(secret, blob)
        page = dashboard.build_html([row], CRIT["activities"], 0.85)
        self.assertNotIn("Khang", page)
        self.assertIn("Không xếp hạng", page)

    def test_detail_renders(self):
        h = report.detail_html(self.res, self.sc, self.meta, NAMES, {"ai_issues": ["x"], "quote_stats": {}, "usage": {}})
        self.assertIn("OB37", h)


class TestCompare(unittest.TestCase):
    def test_compare_with_answer_key_shape(self):
        res, _ = validate.normalize(fake_raw())
        res, _, _ = verify.verify(res, make_tr())
        sc = score.compute(res, CRIT)
        ai = {**res, "scores": sc}
        key = {"criteria": {c: {"expected": "NA"} for c in validate.OB_IDS}, "links": {}, "flags": [{"id": "F09"}]}
        key["criteria"]["OB01"] = {"expected": "FF"}
        key["criteria"]["OB08"] = {"expected": "NF", "accept": ["PF"]}
        key["criteria"]["OB09"] = {"expected": "PF"}
        key["criteria"]["OB02"] = {"expected": "FF"}
        key["criteria"]["OB36"] = {"expected": "NF"}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(key, f)
        out = compare.compare(ai, compare.load_human(Path(f.name)), CRIT)
        m = out["metrics"]
        self.assertAlmostEqual(m["criteria_agreement"], 36 / 37)   # chỉ OB36 lệch (AI hạ NE)
        self.assertAlmostEqual(m["error_recall"], 2 / 3)
        self.assertEqual(m["flags"]["recall"], 1.0)
        md = compare.to_markdown("t1", out, NAMES)
        self.assertIn("Phân loại tiêu chí", md)

    def test_csv_template_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "h.csv"
            compare.write_template(p, CRIT)
            with self.assertRaises(ValueError):           # phiếu chưa điền → báo lỗi, không ra số rỗng
                compare.load_human(p)
            # Excel vi-VN: dấu ";" và nhãn tiếng Việt
            p2 = Path(d) / "h2.csv"
            p2.write_text("ma;ten_buoc;hoat_dong;trang_thai;ghi_chu\nOB01;x;1;Làm đủ;\nOB02;x;1;PF;\nLK01;x;;Chưa đạt;\nF09;x;;co;\n",
                          encoding="utf-8")
            h2 = compare.load_human(p2)
            self.assertEqual(h2["criteria"], {"OB01": ["FF"], "OB02": ["PF"]})
            self.assertEqual(h2["links"], {"LK01": ["CHUA_DAT"]})
            self.assertEqual(h2["flags"], {"F09"})
            p3 = Path(d) / "h3.csv"
            p3.write_text("ma,ten_buoc,hoat_dong,trang_thai,ghi_chu\nOB01,x,1,tốt,\n", encoding="utf-8")
            with self.assertRaises(ValueError):           # giá trị lạ → báo lỗi
                compare.load_human(p3)


class TestPipelineReplay(unittest.TestCase):
    def test_replay_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            tp = Path(d) / "t.json"
            tp.write_text(json.dumps({"segments": [{"start": t, "end": t + 5, "speaker": s, "text": x} for t, s, x in SEGS]},
                                     ensure_ascii=False), encoding="utf-8")
            rp = Path(d) / "raw.json"
            rp.write_text(json.dumps(fake_raw(), ensure_ascii=False), encoding="utf-8")
            script = Path(d) / "script.txt"
            script.write_text("Kịch bản thử", encoding="utf-8")
            import obeval.config as cfg
            old = cfg.SCRIPT_PATH
            prompt_mod_default = prompt.load_script.__defaults__
            prompt.load_script.__defaults__ = (script,)
            try:
                res = pipeline.run_case(tp, {"session_date": "2026-10-09"}, out_root=Path(d) / "out", replay=rp)
            finally:
                prompt.load_script.__defaults__ = prompt_mod_default
                cfg.SCRIPT_PATH = old
            self.assertEqual(res["state"], "done", res)
            case = Path(res["case_dir"])
            for f in ("result.json", "email_mentor.html", "email_mentor.eml", "detail.html", "dashboard_row.json", "status.json"):
                self.assertTrue((case / f).exists(), f)
            rows = dashboard.collect(Path(d) / "out")
            self.assertEqual(len(rows), 1)

    def test_error_case_recorded(self):
        with tempfile.TemporaryDirectory() as d:
            tp = Path(d) / "empty.json"
            tp.write_text(json.dumps({"segments": []}), encoding="utf-8")
            res = pipeline.run_case(tp, {}, out_root=Path(d) / "out", replay=tp)
            self.assertEqual(res["state"], "error")
            row = json.loads((Path(res["case_dir"]) / "dashboard_row.json").read_text(encoding="utf-8"))
            self.assertEqual(row["status"], "error")


class TestEnsemble(unittest.TestCase):
    def _run(self, overrides_by_id: dict, flags=("F09",)):
        raw = fake_raw()
        for c in raw["criteria"]:
            if c["id"] in overrides_by_id:
                c["status"] = overrides_by_id[c["id"]]
        raw["flags"] = [f for f in raw["flags"] if f["id"] in flags]
        res, _ = validate.normalize(raw)
        res, _, _ = verify.verify(res, make_tr())
        return res

    def test_majority_and_median(self):
        r1 = self._run({"OB01": "FF", "OB02": "FF"})
        r2 = self._run({"OB01": "PF", "OB02": "NF"})
        r3 = self._run({"OB01": "FF", "OB02": "PF"}, flags=())
        merged, stab = ensemble_mod.aggregate([r1, r2, r3])
        by = {c["id"]: c for c in merged["criteria"]}
        self.assertEqual(by["OB01"]["status"], "FF")              # đa số 2/3
        self.assertEqual(by["OB02"]["status"], "PF")              # FF/NF/PF → trung vị PF
        self.assertEqual(by["OB02"]["run_statuses"], ["FF", "NF", "PF"])
        self.assertEqual([f["id"] for f in merged["flags"]], ["F09"])  # cờ có ở 2/3 lần
        self.assertIn("OB02", stab["unstable_criteria"])
        self.assertLess(stab["criteria_all_agree"], 1.0)

    def test_two_runs_tie_goes_lower(self):
        r1 = self._run({"OB01": "FF"})
        r2 = self._run({"OB01": "PF"})
        merged, _ = ensemble_mod.aggregate([r1, r2])
        self.assertEqual({c["id"]: c for c in merged["criteria"]}["OB01"]["status"], "PF")

    def test_replay_multi_runs(self):
        with tempfile.TemporaryDirectory() as d:
            tp = Path(d) / "t.json"
            tp.write_text(json.dumps({"segments": [{"start": t, "end": t + 5, "speaker": s, "text": x} for t, s, x in SEGS]},
                                     ensure_ascii=False), encoding="utf-8")
            rp = Path(d) / "raw.json"
            rp.write_text(json.dumps({"runs": [{"data": fake_raw(), "usage": {"prompt_tokens": 10}, "cost_usd_est": 0.1}] * 3},
                                     ensure_ascii=False), encoding="utf-8")
            script = Path(d) / "script.txt"
            script.write_text("Kịch bản thử", encoding="utf-8")
            old = prompt.load_script.__defaults__
            prompt.load_script.__defaults__ = (script,)
            try:
                res = pipeline.run_case(tp, {"session_date": "2026-10-09"}, out_root=Path(d) / "out", replay=rp)
            finally:
                prompt.load_script.__defaults__ = old
            self.assertEqual(res["state"], "done", res)
            self.assertEqual(res["stability"]["criteria_all_agree"], 1.0)
            self.assertEqual(res["cost_usd_est"], 0.3)


class TestReviewRegressions(unittest.TestCase):
    """Các lỗi do review đối kháng 09/10 tìm ra (tool/logs/review-2026-10-09.md)."""

    def _tr(self, segs):
        return transcript.finalize([transcript.Segment(float(t), float(t) + 4, s, x) for t, s, x in segs], "t")

    def test_I1_fabricated_first_evidence_not_in_email(self):
        raw = fake_raw()
        raw["improvements"][0]["evidence"] = [ev("00:10:00", "Mentor", "Thầy hứa sẽ giảm 50% học phí ngay bây giờ"),
                                              ev("00:10:00", "Mentor", "Con khỏe không?")]
        res, _ = validate.normalize(raw)
        res, _, _ = verify.verify(res, make_tr())
        h = report.mentor_email_html(res, score.compute(res, CRIT), {"case_id": "t"}, NAMES)
        self.assertNotIn("giảm 50%", h)
        self.assertIn("Con khỏe không?", h)

    def test_I2_dashboard_no_filename_or_free_text(self):
        raw = fake_raw()
        raw["flags"].append({"id": "Thay Khang", "severity": "low", "explanation": "x", "script_instructed": False,
                             "evidence": [ev("00:00:03", "Mentor", "hai mẹ con nghe rõ tiếng thầy chưa ạ")]})
        raw["improvements"].append({"criterion_id": "XX", "step_name": "Be Minh Anh khong tra loi", "priority": "low",
                                    "evidence": [ev("00:00:03", "Mentor", "hai mẹ con nghe rõ tiếng thầy chưa ạ")],
                                    "problem": "", "logic_impact": "", "suggestion": "", "suggested_script": ""})
        res, _ = validate.normalize(raw)
        res, _, _ = verify.verify(res, make_tr())
        row = dashboard.make_row("2026-10-09_Nguyen-Van-An_Mentor-Khang", {}, res, score.compute(res, CRIT), "done", NAMES)
        blob = json.dumps(row, ensure_ascii=False)
        for leak in ("Khang", "Nguyen", "Minh Anh", "Thay"):
            self.assertNotIn(leak, blob)
        self.assertTrue(row["case_key"].startswith("ca-"))

    def test_I4_no_cross_speaker_or_one_word(self):
        qi = verify.QuoteIndex(self._tr([(1, "SPEAKER_00", "con nhớ đăng ký ngay"), (5, "SPEAKER_01", "không ạ em từ chối")]))
        self.assertEqual(qi.locate("đăng ký ngay không ạ em từ chối")[0], "not_found")
        self.assertEqual(qi.locate("vâng")[0], "too_short")
        self.assertEqual(qi.locate("con nhớ đăng ký ngay")[0], "exact")

    def test_I5_repeated_quote_nearest_timestamp(self):
        tr = self._tr([(10, "S1", "Dạ vâng ạ thầy"), (300, "S0", "Mình qua phần sau"), (500, "S1", "Dạ vâng ạ thầy")])
        e2 = verify.check_evidence(ev("00:08:20", "PH", "Dạ vâng ạ thầy"), verify.QuoteIndex(tr))
        self.assertEqual(e2["timestamp"], "00:08:20")
        self.assertFalse(e2.get("timestamp_corrected", False))

    def test_I6_masking(self):
        cases = {
            "gọi 0912,345,678 nhé": True, "STK 1234 5678 9012": True, "zalo 0912.345.678": True,
            "học phí 120000000 đồng": False, "học phí 120.000.000": False, "1.000.000.000 đồng": False,
            "lớp 7 năm 2026": False, "mã TC13187": False,
        }
        for text, should_mask in cases.items():
            out, n = transcript.mask_numbers(text)
            self.assertEqual(n > 0, should_mask, f"{text!r} → {out!r}")
        tr = transcript.finalize([transcript.Segment(1.0, 2.0, "+84 912 345 678", "xin chào")], "t")
        self.assertNotIn("912", transcript.render(tr))

    def _load(self, content, suffix, fmt="auto"):
        with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8") as f:
            f.write(content)
        return transcript.load(f.name, fmt)

    def test_I7_formats(self):
        vtt = self._load("WEBVTT\n\n00:01.000 --> 00:03.000\n<v Mentor>Chào em</v>\n", ".vtt")
        self.assertEqual((vtt.source_format, vtt.segments[0].speaker, vtt.segments[0].text), ("srt_vtt", "Mentor", "Chào em"))
        db = self._load(json.dumps({"transcript": json.dumps([{"text": "a b", "start_time": 5}])}), ".json")
        self.assertEqual(db.segments[0].start, 5.0)
        meet = self._load("00:00:00\nMentor: Có ba bước\nbước một là: hỏi gia đình\n00:01:00\nMentor: tiếp\n", ".txt")
        self.assertEqual([s.speaker for s in meet.segments], ["Mentor", "Mentor"])
        forced = self._load("00:00:05\nThầy Khang: Chào\n", ".txt", fmt="meet")
        self.assertEqual((forced.source_format, forced.segments[0].start), ("meet_text", 5.0))

    def test_M1_case_key_unique(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "x" / "rec.json", Path(d) / "y" / "rec.json"
            self.assertNotEqual(pipeline.case_key_from(a, "2026-10-09"), pipeline.case_key_from(b, "2026-10-09"))
            self.assertIn("Dang-Van", pipeline.case_key_from(Path(d) / "Đặng Văn.json", "2026-10-09"))

    def test_M2_rescore_without_raw_keeps_case(self):
        with tempfile.TemporaryDirectory() as d:
            case = Path(d) / "c1"
            case.mkdir()
            (case / "result.json").write_text("{}", encoding="utf-8")
            res = pipeline.rescore(case)
            self.assertEqual(res["state"], "error")
            self.assertFalse((case / "dashboard_row.json").exists())

    def test_M3_script_breakout(self):
        page = dashboard.build_html([{"case_key": "<!--<script>", "status": "done"}], CRIT["activities"], 0.85)
        self.assertNotIn("<!--<script>", page)

    def test_tone_mark_variants(self):
        qi = verify.QuoteIndex(self._tr([(1, "S0", "gia đình mình rất hoà thuận và vui vẻ")]))
        self.assertEqual(qi.locate("gia đình mình rất hòa thuận")[0], "exact")


class TestReviewRound2(unittest.TestCase):
    """Lỗi review vòng 2 (tool/logs/review-2026-10-09-v2.md)."""

    def _tr(self, segs):
        return transcript.finalize([transcript.Segment(float(t), float(t) + 4, s, x) for t, s, x in segs], "t")

    def _checked(self, raw):
        res, _ = validate.normalize(raw)
        res, _, _ = verify.verify(res, make_tr())
        return res

    def test_N1_text_consistent_with_merged_status(self):
        r1, r2, r3 = (self._checked(fake_raw()) for _ in range(3))
        for r in (r1, r2):  # đa số chấm OB08 = FF → gợi ý về OB08 phải biến mất
            next(c for c in r["criteria"] if c["id"] == "OB08")["status"] = "FF"
        merged, _ = ensemble_mod.aggregate([r3, r1, r2])
        self.assertEqual({c["id"]: c["status"] for c in merged["criteria"]}["OB08"], "FF")
        self.assertNotIn("OB08", [i["criterion_id"] for i in merged["improvements"]])
        st = {c["id"]: c["status"] for c in merged["criteria"]}
        self.assertTrue(all(st[s["criterion_id"]] == "FF" for s in merged["strengths"]))

    def test_N2_insufficient_majority_order_independent(self):
        rs = [self._checked(fake_raw()) for _ in range(3)]
        rs[0]["data_quality"]["insufficient_data"] = True
        a, _ = ensemble_mod.aggregate([rs[0], rs[1], rs[2]])
        b, _ = ensemble_mod.aggregate([rs[1], rs[2], rs[0]])
        self.assertEqual(a["data_quality"]["insufficient_data"], b["data_quality"]["insufficient_data"])
        self.assertFalse(a["data_quality"]["insufficient_data"])

    def test_N3_fuzzy_rejects_negation_and_number_changes(self):
        qi = verify.QuoteIndex(self._tr([(1, "S0", "ưu đãi này kéo dài trong 48 giờ nên mẹ không cần quyết định ngay hôm nay đâu ạ")]))
        self.assertEqual(qi.locate("ưu đãi này kéo dài trong 24 giờ nên mẹ không cần quyết định ngay hôm nay")[0], "not_found")
        self.assertEqual(qi.locate("ưu đãi này kéo dài trong 48 giờ nên mẹ cần quyết định ngay hôm nay đâu ạ")[0], "not_found")
        ev2 = verify.check_evidence({"timestamp": "00:00:01", "speaker": "Mentor",
                                     "quote": "ưu đãi này kéo dài trong 48 tiếng nên mẹ không cần quyết định ngay hôm nay"}, qi)
        self.assertEqual(ev2["match"], "fuzzy")
        self.assertIn("48 giờ", ev2["quote"])                 # email in lời gốc
        self.assertIn("48 tiếng", ev2["quote_model"])

    def test_N3b_window_trim_cannot_drop_negation(self):
        qi = verify.QuoteIndex(self._tr([(1, "S0", "Thầy không hứa con sẽ đỗ trường chuyên đâu chị nhé"),
                                         (9, "S0", "Thầy chưa nói về học phí với gia đình mình")]))
        self.assertEqual(qi.locate("Thầy hứa con sẽ đỗ trường chuyên đâu chị nhé")[0], "not_found")
        self.assertEqual(qi.locate("Thầy đã nói về học phí với gia đình mình")[0], "not_found")

    def test_L1_negation_two_words_outside_window(self):
        qi = verify.QuoteIndex(self._tr([(1, "S0", "Thầy không dám cam kết là con chắc chắn sẽ đỗ trường chuyên đâu chị ạ")]))
        self.assertEqual(qi.locate("Thầy cam kết là con chắc chắn sẽ đỗ trường chuyên đâu chị ạ")[0], "not_found")

    def test_L1b_trailing_question_particle_ok(self):
        qi = verify.QuoteIndex(self._tr([(1, "S0", "con có hay bị căng thẳn khi đi thi không")]))  # STT thiếu "g"
        self.assertEqual(qi.locate("con có hay bị căng thẳng khi đi thi")[0], "fuzzy")
        qi2 = verify.QuoteIndex(self._tr([(1, "S0", "các khối lớp học tập theo nhóm rất vui vẻ và hiệu quả")]))
        self.assertEqual(qi2.locate("các khối lớp học tập theo nhóm rất vui và hiệu quả")[0], "fuzzy")  # "khối" ≠ "khỏi"

    def test_L2_meet_continuation_single_word(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("00:00:00\nThầy Khang: Hôm nay mình ôn ba môn\nToán: hàm số bậc nhất\nLưu ý: làm bài tập\n"
                    "Nguyễn thị Thu: Dạ vâng\n00:01:00\nThầy Khang: Tiếp nhé\n")
        segs = transcript.load(f.name).segments
        self.assertEqual([s.speaker for s in segs], ["Thầy Khang", "Nguyễn thị Thu", "Thầy Khang"])
        self.assertIn("Toán: hàm số", segs[0].text)

    def test_N6b_phone_before_unit_like_word(self):
        for text in ("gọi 0912345678 k chị", "gọi 0912345678 tr ưa"):
            self.assertGreater(transcript.mask_numbers(text)[1], 0, text)

    def test_N7b_meet_single_occurrence_name(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("00:00:00\nThầy Khang: Chào cả nhà\nNguyễn thị Thu: Dạ nghe rõ ạ\n00:05:00\nThầy Khang: Mình bắt đầu\n")
        self.assertEqual([s.speaker for s in transcript.load(f.name).segments], ["Thầy Khang", "Nguyễn thị Thu", "Thầy Khang"])

    def test_N4_ellipsis_cannot_stitch_single_words(self):
        qi = verify.QuoteIndex(self._tr([(1, "S0", "thầy nghĩ là con sẽ thi đỗ thôi"), (5, "S1", "dạ để chị chốt với ba cháu")]))
        self.assertEqual(qi.locate("thầy … đỗ … chốt")[0], "too_short")
        self.assertEqual(qi.locate("thầy nghĩ là … sẽ thi đỗ thôi")[0], "exact")
        self.assertEqual(qi.locate("con sẽ thi đỗ … để chị chốt với ba")[0], "not_found")  # 2 người nói qua "…"

    def test_N5_stt_slip_tolerated(self):
        qi = verify.QuoteIndex(self._tr([(1, "S0", "con hãy thử ghi lại cảm xúc mỗi tối trước khi đi"), (6, "S1", "ngủ nhé con")]))
        self.assertEqual(qi.locate("con hãy thử ghi lại cảm xúc mỗi tối trước khi đi ngủ nhé con")[0], "exact")

    def test_N6_masking_more_forms(self):
        for text in ("84 912 345 678", "(+84) 912 345 678", "gọi 912 345 678", "stk 190 345 678 901", "sdt0912345678"):
            out, n = transcript.mask_numbers(text)
            self.assertGreater(n, 0, f"{text!r} → {out!r}")
        for text in ("tổng 36.000.000 12.000.000", "điểm 8 9 7 8 9 10 9 8 7", "học phí 120.000.000"):
            out, n = transcript.mask_numbers(text)
            self.assertEqual(n, 0, f"{text!r} → {out!r}")

    def test_N7_meet_lowercase_names(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("00:00:00\nThầy Khang: Chào cả nhà\nNguyễn thị Thu: Dạ chào thầy\n00:01:00\n"
                    "Thầy Khang: Bước một là: hỏi gia đình\nNguyễn thị Thu: Dạ vâng\nmẹ bé An: con chào thầy\nBước 1: không phải người nói\n")
        tr = transcript.load(f.name)
        self.assertEqual([s.speaker for s in tr.segments], ["Thầy Khang", "Nguyễn thị Thu", "Thầy Khang", "Nguyễn thị Thu", "mẹ bé An"])

    def test_Ma_rescore_missing_transcript(self):
        with tempfile.TemporaryDirectory() as d:
            case = Path(d) / "c1"
            case.mkdir()
            (case / "model_raw.json").write_text("{}", encoding="utf-8")
            (case / "result.json").write_text(json.dumps({"meta": {"transcript_path": str(Path(d) / "gone.json")}}), encoding="utf-8")
            self.assertEqual(pipeline.rescore(case)["state"], "error")
            self.assertFalse((case / "dashboard_row.json").exists())

    def test_Mb_collect_sanitizes_old_rows(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "x").mkdir()
            (Path(d) / "x" / "dashboard_row.json").write_text(json.dumps({
                "case_key": "2026_Thay-Khang", "status": "done", "transcript_coverage": "partial - Thầy Khang nói nhỏ",
                "flags": [{"id": "Thay Khang", "name": "Thay Khang"}],
                "improvement_steps": [{"id": "XX", "name": "Be Minh Anh"}]}, ensure_ascii=False), encoding="utf-8")
            rows = dashboard.collect(Path(d), NAMES)
            blob = json.dumps(rows, ensure_ascii=False)
            for leak in ("Khang", "Minh Anh"):
                self.assertNotIn(leak, blob)

    def test_Mc_enum_normalized(self):
        raw = fake_raw()
        raw["data_quality"]["transcript_coverage"] = "partial - bé Minh Anh nói nhỏ"
        raw["sequence"]["status"] = "lệch vì Thầy Khang"
        res, _ = validate.normalize(raw)
        self.assertEqual(res["data_quality"]["transcript_coverage"], "partial")
        self.assertEqual(res["sequence"]["status"], "KHONG_DU_DU_LIEU")

    def test_Md_vote_two_runs(self):
        self.assertEqual(ensemble_mod._vote(["FF", "NA"], ensemble_mod.CRIT_ORDER, "NE"), "FF")
        self.assertEqual(ensemble_mod._vote(["NE", "NA"], ensemble_mod.CRIT_ORDER, "NE"), "NE")

    def test_Me_flags_unverified_dedup(self):
        rs = [self._checked(fake_raw()) for _ in range(3)]  # mỗi lần: F09 giữ, F01 bịa bị loại
        merged, _ = ensemble_mod.aggregate(rs)
        ids = [f["id"] for f in merged["flags_unverified"]]
        self.assertEqual(ids, ["F01"])
        self.assertEqual(merged["flags_unverified"][0]["runs"], 3)

    def test_Mk_humanize_parentheses(self):
        out = NAMES.humanize("xem lại (OB27, OB28) nhé")
        self.assertEqual(out.count("("), out.count(")"))
        self.assertNotIn("OB27", out)

    def test_Ml_compare_link_alias_and_ansi(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "h.csv"
            p.write_text("ma,ten_buoc,hoat_dong,trang_thai,ghi_chu\nOB01,x,1,FF,\nLK01,x,,Không đủ dữ liệu,\n", encoding="utf-8")
            self.assertEqual(compare.load_human(p)["links"], {"LK01": ["KHONG_DU_DU_LIEU"]})
            # Excel ANSI (cp1258): dấu thanh lưu dạng tổ hợp "a" + U+0323
            p.write_bytes("ma,ten_buoc,hoat_dong,trang_thai,ghi_chu\nOB01,x,1,FF,\nLK01,x,,Đạt,\n".encode("cp1258"))
            self.assertEqual(compare.load_human(p)["links"], {"LK01": ["DAT"]})

    def test_email_page_declares_utf8(self):
        res = self._checked(fake_raw())
        page = report.mentor_email_page(res, score.compute(res, CRIT), {"case_id": "t"}, NAMES)
        self.assertIn("<meta charset='utf-8'>", page)


if __name__ == "__main__":
    unittest.main()

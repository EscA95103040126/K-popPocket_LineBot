from datetime import date

from scripts.refresh_monthly_analysis import aggregate_comments, artist_matches, local_day
from src.agent import KpopAnalysisAgent, _extract_artist_name, _insight_from_absa
from src.tools.absa import format_absa_report_for_line


def test_monthly_dates_use_taipei_boundary():
    assert local_day("2026-09-30T16:00:00Z") == date(2026, 10, 1)
    assert local_day("2026-10-11T16:00:00Z") == date(2026, 10, 12)


def test_sample_overall_and_aspect_sentiments_are_separate():
    comments = [{"comment": "보컬은 좋아 안무는 별로", "link": "https://example.com/1",
                 "published_at": "2026-10-01T01:00:00Z"},
                {"comment": "응원해", "link": "https://example.com/2",
                 "published_at": "2026-10-02T01:00:00Z"}]
    annotations = [{"id": 0, "sentiment": "neutral", "aspects": [
        {"aspect": "vocal_rap", "sentiment": "positive"},
        {"aspect": "performance", "sentiment": "negative"}]},
        {"id": 1, "sentiment": "positive", "aspects": [
            {"aspect": "fandom_public_opinion", "sentiment": "positive"}]}]
    overall, aspects = aggregate_comments(comments, annotations)
    assert overall["count"] == 2
    assert overall["ratio"]["positive"] == 0.5
    assert aspects["vocal_rap"]["ratio"]["positive"] == 1
    assert aspects["performance"]["ratio"]["negative"] == 1
    assert aspects["visual_styling"]["count"] == 0


def test_monthly_report_keeps_snapshot_instead_of_unrelated_latest_chart():
    payload = {"analysis_period": {"start": "2026-10-01", "end": "2026-10-11"},
               "monthly_insight": {"headline": "截至日分析", "risk": "中", "opportunity": "觀察新週榜"},
               "report_text": "10月報告：9/28–10/4，留言樣本不足"}
    assert format_absa_report_for_line(payload, "過期或未來榜單") == payload["report_text"]
    assert _insight_from_absa(payload)["risk"] == "中"


def test_artist_aliases_exclude_unrelated_acronyms():
    assert artist_matches("TXT", "TOMORROW X TOGETHER official")
    assert artist_matches("NCT", "NCT DREAM")
    assert not artist_matches("IVE", "LIVE MUSIC")


def test_monthly_cache_uses_the_published_chart_snapshot():
    class NoChartAccess:
        def get_latest_weekly_chart(self, **kwargs):
            raise AssertionError("Monthly reports must retain their source snapshot")

    agent = KpopAnalysisAgent(chart_repo=NoChartAccess())
    payload = {"artist": "NCT", "generated_at": "2026-10-11T12:00:00Z",
               "analysis_period": {"start": "2026-10-01", "end": "2026-10-11"},
               "monthly_insight": {"headline": "分隊觀察", "risk": "資料不足", "opportunity": "拆分分隊"},
               "sources": {"bugs_chart": {"chart_start": "2026-09-28", "items": []}},
               "report_text": "# NCT 2026-10 市場與輿論分析\n\n## 5. 一句話總結\n分隊資料不同"}
    cached = agent._artist_cache_from_absa(payload)
    assert cached["sources"]["chart"]["chart_date"] == "2026-09-28"
    assert cached["analysis_period"] == payload["analysis_period"]
    assert cached["period_months"] == 1
    assert cached["insight"]["risk"] == "資料不足"
    assert _extract_artist_name(cached["report"]) == "NCT"

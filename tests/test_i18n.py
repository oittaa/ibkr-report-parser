"""Tests for UI language detection and catalogs."""

import unittest
from unittest.mock import patch

from ibkr_report import create_app
from ibkr_report.i18n import detect_lang, normalize_lang, t

THIS_PATH_DATA = "tests/test-data/data_single_account.csv"


class DetectLangTests(unittest.TestCase):
    def test_normalize_lang(self):
        self.assertEqual(normalize_lang("fi"), "fi")
        self.assertEqual(normalize_lang("FI-fi"), "fi")
        self.assertEqual(normalize_lang("en_US"), "en")
        self.assertIsNone(normalize_lang("sv"))
        self.assertIsNone(normalize_lang(""))
        self.assertIsNone(normalize_lang(None))

    def test_detect_priority(self):
        self.assertEqual(detect_lang(query_lang="fi"), "fi")
        self.assertEqual(
            detect_lang(query_lang="en", cookie_lang="fi", accept_language="fi"),
            "en",
        )
        self.assertEqual(detect_lang(cookie_lang="fi", accept_language="en"), "fi")
        self.assertEqual(detect_lang(accept_language="fi-FI,fi;q=0.9,en;q=0.8"), "fi")
        self.assertEqual(detect_lang(accept_language="sv,de"), "en")
        self.assertEqual(detect_lang(), "en")

    def test_t_fallback_and_format(self):
        self.assertIn("Total selling prices", t("en", "result.total_selling_prices"))
        self.assertEqual(
            t("fi", "result.total_selling_prices"), "Luovutushinnat yhteensä"
        )
        self.assertIn(
            "2021",
            t(
                "en",
                "result.report_year",
                report_year=2021,
                file_count=1,
                file_plural="",
            ),
        )
        self.assertEqual(t("en", "missing.key"), "missing.key")


@patch(
    "ibkr_report.exchangerates.EXCHANGE_RATES_URL",
    f"file://{__import__('os').path.abspath('tests/test-data/eurofxref-hist.zip')}",
)
class WebsiteI18nTests(unittest.TestCase):
    def setUp(self):
        app = create_app()
        self.app = app.test_client()

    def test_default_english(self):
        response = self.app.get("/", headers={"Accept-Language": "en"})
        self.assertEqual(response.status_code, 200)
        html = response.data.decode("utf-8")
        self.assertIn('lang="en"', html)
        self.assertIn("Choose file(s)", html)
        self.assertNotIn("Valitse tiedosto(t)", html)
        self.assertIn('class="lang-current"', html)

    def test_accept_language_finnish(self):
        response = self.app.get("/", headers={"Accept-Language": "fi-FI,fi;q=0.9"})
        self.assertEqual(response.status_code, 200)
        html = response.data.decode("utf-8")
        self.assertIn('lang="fi"', html)
        self.assertIn("Valitse tiedosto(t)", html)
        self.assertIn("Lähdekoodi GitHubissa", html)
        self.assertNotIn("Choose file(s)", html)

    def test_query_lang_sets_cookie_and_redirects(self):
        response = self.app.get("/?lang=fi", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("lang=fi", response.headers.get("Set-Cookie", ""))
        response = self.app.get("/?lang=fi", follow_redirects=True)
        html = response.data.decode("utf-8")
        self.assertIn('lang="fi"', html)
        self.assertIn("Valitse tiedosto(t)", html)

    def test_cookie_overrides_accept_language(self):
        self.app.set_cookie("lang", "en")
        response = self.app.get("/", headers={"Accept-Language": "fi"})
        html = response.data.decode("utf-8")
        self.assertIn('lang="en"', html)
        self.assertIn("Choose file(s)", html)

    def test_invalid_query_lang_ignored(self):
        response = self.app.get("/?lang=sv", follow_redirects=False)
        # Invalid lang is not a preference change; page renders with default detection.
        self.assertEqual(response.status_code, 200)
        html = response.data.decode("utf-8")
        self.assertIn('lang="en"', html)

    def test_result_finnish_labels(self):
        self.app.set_cookie("lang", "fi")
        with open(THIS_PATH_DATA, "rb") as handle:
            response = self.app.post("/result", data={"file": handle})
        self.assertEqual(response.status_code, 200)
        html = response.data.decode("utf-8")
        self.assertIn("Luovutushinnat yhteensä", html)
        self.assertIn("Hankintapäivä", html)
        self.assertIn("Arvopaperien myyntivoitot", html)
        self.assertNotIn("Total selling prices /", html)
        self.assertNotIn("Acquisition date /", html)

    def test_result_english_labels(self):
        self.app.set_cookie("lang", "en")
        with open(THIS_PATH_DATA, "rb") as handle:
            response = self.app.post("/result", data={"file": handle})
        self.assertEqual(response.status_code, 200)
        html = response.data.decode("utf-8")
        self.assertIn("Total selling prices", html)
        self.assertIn("Date when acquired", html)
        self.assertIn("Profits from selling securities", html)
        self.assertNotIn("Luovutushinnat yhteensä", html)

    def test_error_page_finnish_chrome(self):
        self.app.set_cookie("lang", "fi")
        with open("tests/test-data/data_invalid_date.csv", "rb") as handle:
            response = self.app.post("/result", data={"file": handle})
        self.assertEqual(response.status_code, 400)
        html = response.data.decode("utf-8")
        self.assertIn("VIRHE", html)
        self.assertIn("Takaisin", html)


if __name__ == "__main__":
    unittest.main()

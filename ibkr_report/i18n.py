"""Lightweight Finnish/English UI translations for the web interface."""

from __future__ import annotations

from typing import Any, Callable, Mapping, Optional

from werkzeug.datastructures import LanguageAccept
from werkzeug.http import parse_accept_header

SUPPORTED_LANGS = ("en", "fi")
DEFAULT_LANG = "en"
LANG_COOKIE = "lang"
LANG_COOKIE_MAX_AGE = 365 * 24 * 60 * 60  # 1 year

# Message catalogs. Prefer official form 9A / MyTax wording where applicable.
# IBKR product UI labels stay in English in both locales.
_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "lang.switcher_label": "Language",
        "lang.en": "English",
        "lang.fi": "Finnish",
        "error.suffix": "ERROR",
        "error.back": "Back",
        "index.disclaimer": (
            'This site is not affiliated with <a href="https://www.interactivebrokers.com/">'
            'Interactive Brokers</a> or <a href="https://vero.fi/">the Finnish Tax Administration '
            "(Verohallinto)</a>. The information contained in this site is provided on an "
            '"as is" basis with no guarantees of completeness, accuracy, usefulness or '
            "timeliness and without any warranties of any kind whatsoever, express or implied."
        ),
        "index.source_code": "Source code at GitHub",
        "index.step1_title": "1. Download a CSV trades report from Interactive Brokers.",
        "index.steps_header": "Steps",
        "index.step1_reports": (
            "Go to <strong>Reports</strong> &rarr; <strong>Statements</strong>."
        ),
        "index.step1_custom": "Create a new <strong>Custom Statement</strong>.",
        "index.step1_sections": (
            "From <strong>Sections</strong> select <strong>Trades</strong>."
        ),
        "index.step1_hide_details": (
            "From <strong>Section Configurations</strong> make sure "
            "<strong>Hide Details for Positions, Trades and Client Fees Sections?</strong> is "
            "set to <strong>No</strong>."
        ),
        "index.step1_img_sections_alt": "Sections: Trades",
        "index.step1_run_csv": (
            "After saving the statement, run it with a <strong>CSV</strong> output."
        ),
        "index.step1_img_csv_alt": "Format: CSV",
        "index.step2_title": "2. Upload the CSV file(s).",
        "index.step2_help": (
            "You can select multiple years (or a multi-year custom statement). The report uses "
            "disposals from the <strong>latest year</strong> in the data; earlier years still "
            "supply option premiums for stock lots closed later (e.g. puts assigned in a prior "
            "year)."
        ),
        "index.choose_files": "Choose file(s)",
        "result.step3_title": (
            '3. Fill out the forms at <a href="https://vero.fi/">vero.fi</a> (MyTax)'
        ),
        "result.report_year": (
            "<strong>Report year {report_year}</strong> from {file_count} uploaded "
            "file{file_plural}."
        ),
        "result.section_title": "Profits from selling securities",
        "result.filing_help": (
            "From <strong>Filing method</strong> choose "
            "<strong>I am giving the details on securities in an attachment file</strong> "
            "and fill out the following fields."
        ),
        "result.field": "Field",
        "result.value": "Value",
        "result.total_selling_prices": "Total selling prices",
        "result.total_capital_gains": "Total capital gains",
        "result.total_capital_losses": "Total capital losses",
        "result.details": "Details",
        "result.name_of_security": "Name of security",
        "result.quantity": "Quantity",
        "result.date_when_acquired": "Date when acquired",
        "result.acquisition_price": "Acquisition price",
        "result.deemed_acquisition_cost": "Deemed acquisition cost",
        "result.deemed_short": "Deemed",
        "result.selling_date": "Selling date",
        "result.selling_price": "Selling price",
        "result.capital_gain_or_loss": "Capital gain or capital loss",
        "result.title_date_when_acquired": "Form 9A: Date when acquired",
        "result.title_acquisition_price": (
            "Form 9A: Acquisition price (total acquisition cost in report currency)"
        ),
        "result.title_deemed": "Deemed acquisition cost applied",
        "result.title_selling_date": "Form 9A: Selling date",
        "result.title_selling_price": (
            "Form 9A: Selling price (total selling price in report currency)"
        ),
        "result.title_gain_or_loss": "Form 9A: Capital gain / capital loss",
    },
    "fi": {
        "lang.switcher_label": "Kieli",
        "lang.en": "English",
        "lang.fi": "Suomi",
        "error.suffix": "VIRHE",
        "error.back": "Takaisin",
        "index.disclaimer": (
            'Tämä sivusto ei ole yhteydessä <a href="https://www.interactivebrokers.com/">'
            'Interactive Brokersiin</a> eikä <a href="https://vero.fi/">Verohallintoon</a>. '
            "Sivuston sisältö tarjotaan sellaisenaan ilman takuita täydellisyydestä, "
            "oikeellisuudesta, hyödyllisyydestä tai ajantasaisuudesta, eikä minkäänlaisia "
            "nimenomaisia tai oletettuja takuita."
        ),
        "index.source_code": "Lähdekoodi GitHubissa",
        "index.step1_title": (
            "1. Lataa CSV-muotoinen kaupparaportti Interactive Brokersista."
        ),
        "index.steps_header": "Vaiheet",
        "index.step1_reports": (
            "Siirry kohtaan <strong>Reports</strong> &rarr; <strong>Statements</strong>."
        ),
        "index.step1_custom": "Luo uusi <strong>Custom Statement</strong>.",
        "index.step1_sections": (
            "Valitse kohdasta <strong>Sections</strong> kohta <strong>Trades</strong>."
        ),
        "index.step1_hide_details": (
            "Varmista kohdasta <strong>Section Configurations</strong>, että "
            "<strong>Hide Details for Positions, Trades and Client Fees Sections?</strong> on "
            "asetettu arvoon <strong>No</strong>."
        ),
        "index.step1_img_sections_alt": "Sections: Trades",
        "index.step1_run_csv": (
            "Tallenna statement ja aja se <strong>CSV</strong>-muodossa."
        ),
        "index.step1_img_csv_alt": "Format: CSV",
        "index.step2_title": "2. Lataa CSV-tiedosto(t).",
        "index.step2_help": (
            "Voit valita useita vuosia (tai monivuotisen custom statementin). Raportti käyttää "
            "luovutuksia datan <strong>viimeisimmältä vuodelta</strong>; aiemmat vuodet "
            "toimittavat silti optiopreemiot myöhemmin suljetuille osake-erille "
            "(esim. edellisenä vuonna assigoidut put-optiot)."
        ),
        "index.choose_files": "Valitse tiedosto(t)",
        "result.step3_title": (
            '3. Täytä lomakkeet osoitteessa <a href="https://vero.fi/">vero.fi</a> (OmaVero)'
        ),
        "result.report_year": (
            "<strong>Verovuosi {report_year}</strong>, {file_count} ladattua "
            "tiedostoa."
        ),
        "result.section_title": "Arvopaperien myyntivoitot",
        "result.filing_help": (
            "Valitse kohdasta <strong>Ilmoittamistapa</strong> vaihtoehto "
            "<strong>Ilmoitan arvopaperien tiedot liitetiedostossa</strong> "
            "ja täytä seuraavat kentät."
        ),
        "result.field": "Kenttä",
        "result.value": "Arvo",
        "result.total_selling_prices": "Luovutushinnat yhteensä",
        "result.total_capital_gains": "Luovutusvoitot yhteensä",
        "result.total_capital_losses": "Luovutustappiot yhteensä",
        "result.details": "Tiedot",
        "result.name_of_security": "Arvopaperin nimi",
        "result.quantity": "Kappalemäärä",
        "result.date_when_acquired": "Hankintapäivä",
        "result.acquisition_price": "Hankintahinta",
        "result.deemed_acquisition_cost": "Hankintameno-olettama",
        "result.deemed_short": "Olettama",
        "result.selling_date": "Luovutuspäivä",
        "result.selling_price": "Luovutushinta",
        "result.capital_gain_or_loss": "Luovutusvoitto tai -tappio",
        "result.title_date_when_acquired": "Lomake 9A: Hankintapäivä",
        "result.title_acquisition_price": (
            "Lomake 9A: Hankintahinta (hankintameno raportin valuutassa)"
        ),
        "result.title_deemed": "Hankintameno-olettamaa käytetty",
        "result.title_selling_date": "Lomake 9A: Luovutuspäivä",
        "result.title_selling_price": (
            "Lomake 9A: Luovutushinta (myyntihinta raportin valuutassa)"
        ),
        "result.title_gain_or_loss": "Lomake 9A: Luovutusvoitto / luovutustappio",
    },
}


def normalize_lang(value: Optional[str]) -> Optional[str]:
    """Return a supported language code, or None if value is missing/unsupported."""
    if not value:
        return None
    code = value.strip().lower().replace("_", "-")
    if not code:
        return None
    primary = code.split("-", 1)[0]
    if primary in SUPPORTED_LANGS:
        return primary
    return None


def detect_lang(
    query_lang: Optional[str] = None,
    cookie_lang: Optional[str] = None,
    accept_language: Optional[str] = None,
) -> str:
    """Resolve language: query → cookie → Accept-Language → default English."""
    for candidate in (query_lang, cookie_lang):
        lang = normalize_lang(candidate)
        if lang:
            return lang

    if accept_language:
        # Accept-Language is e.g. "fi-FI,fi;q=0.9,en;q=0.8".
        accept = parse_accept_header(accept_language, LanguageAccept)
        matched = accept.best_match(list(SUPPORTED_LANGS))
        if matched:
            return matched

    return DEFAULT_LANG


def detect_lang_from_request(request: Any) -> str:
    """Detect language from a Flask/Werkzeug request."""
    return detect_lang(
        query_lang=request.args.get("lang"),
        cookie_lang=request.cookies.get(LANG_COOKIE),
        accept_language=request.headers.get("Accept-Language"),
    )


def get_strings(lang: str) -> Mapping[str, str]:
    """Return the message map for a language (falls back to English)."""
    return _STRINGS.get(lang, _STRINGS[DEFAULT_LANG])


def t(lang: str, key: str, **kwargs: object) -> str:
    """Translate a message key, with optional str.format kwargs."""
    catalog = get_strings(lang)
    fallback = _STRINGS[DEFAULT_LANG]
    text = catalog.get(key) or fallback.get(key) or key
    if kwargs:
        return text.format(**kwargs)
    return text


def make_translator(lang: str) -> Callable[..., str]:
    """Return a t(key, **kwargs) function bound to lang."""

    def _t(key: str, **kwargs: object) -> str:
        return t(lang, key, **kwargs)

    return _t

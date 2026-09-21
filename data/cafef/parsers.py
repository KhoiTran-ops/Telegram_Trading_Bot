"""Conservative parsers: preserve raw values and never impute missing data."""

from html.parser import HTMLParser
import re


class _DirectTableRows(HTMLParser):
    def __init__(self, table_id: str) -> None:
        super().__init__(convert_charrefs=True)
        self.table_id = table_id
        self.depth = 0
        self.in_row = False
        self.in_cell = False
        self.cell_parts: list[str] = []
        self.row: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "table":
            if self.depth:
                self.depth += 1
            elif attributes.get("id") == self.table_id:
                self.depth = 1
            return
        if self.depth != 1:
            return
        if tag == "tr":
            self.in_row = True
            self.row = []
        elif tag in {"td", "th"} and self.in_row:
            self.in_cell = True
            self.cell_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self.depth:
            self.depth -= 1
            return
        if self.depth != 1:
            return
        if tag in {"td", "th"} and self.in_cell:
            self.row.append(" ".join("".join(self.cell_parts).replace("\xa0", " ").split()))
            self.in_cell = False
        elif tag == "tr" and self.in_row:
            self.rows.append(self.row)
            self.in_row = False

    def handle_data(self, data: str) -> None:
        if self.depth == 1 and self.in_cell:
            self.cell_parts.append(data)


def _direct_rows(html: str, table_id: str) -> list[list[str]]:
    parser = _DirectTableRows(table_id)
    parser.feed(html)
    return parser.rows


def parse_financial_number(raw: str) -> int | float | None:
    value = raw.strip()
    if not value or value in {"-", "--", "N/A"}:
        return None
    normalized = value.replace(".", "").replace(",", ".").replace(" ", "")
    if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", normalized):
        return None
    number = float(normalized)
    return int(number) if number.is_integer() else number


def parse_financial_statement(html: str) -> list[dict[str, object]]:
    grid_rows = _direct_rows(html, "tblGridData")
    if not grid_rows:
        return []
    headers = grid_rows[0]
    periods = []
    for cell in headers[1:]:
        match = re.search(r"Quý\s*([1-4])\s*-\s*((?:19|20)\d{2})", cell,
                          re.IGNORECASE)
        if match:
            periods.append((int(match.group(2)), int(match.group(1))))
    if not periods:
        return []

    facts: list[dict[str, object]] = []
    for row_order, cells in enumerate(_direct_rows(html, "tableContent")):
        if not cells or not cells[0]:
            continue
        values = {
            period: (raw, parse_financial_number(raw))
            for period, raw in zip(periods, cells[1:], strict=False)
        }
        facts.append({"row_order": row_order, "item_name": cells[0], "values": values})
    return facts


def parse_financial_periods(payload: object) -> tuple[list[dict[str, object]], int]:
    """Extract unique quarterly periods and their audit status from CafeF's API."""
    if not isinstance(payload, dict) or payload.get("isSuccess") is not True:
        raise ValueError("CafeF financial summary was unsuccessful")
    value = payload.get("value")
    if not isinstance(value, dict) or not isinstance(value.get("data"), list):
        raise ValueError("CafeF financial summary schema changed")
    periods: dict[tuple[str, int, int], dict[str, object]] = {}
    for section in value["data"]:
        if not isinstance(section, dict) or not isinstance(section.get("data"), list):
            continue
        for period in section["data"]:
            if not isinstance(period, dict):
                continue
            symbol = str(period.get("symbol") or "").upper()
            year = int(period.get("year") or 0)
            quarter = int(period.get("quater") or 0)
            if not symbol or not year or quarter not in range(1, 5):
                continue
            status = str(period.get("content") or "").strip()
            periods[(symbol, year, quarter)] = {
                "symbol": symbol, "fiscal_year": year, "fiscal_quarter": quarter,
                "audit_status": status,
                "is_audited": status.casefold() == "đã kiểm toán".casefold(),
                "report_code": str(period.get("type") or ""),
            }
    return list(periods.values()), int(value.get("count") or len(periods))

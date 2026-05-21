import re

from decoy import DECOY_DATA, DECOY_DB
from packets import ok_packet, result_set


class QueryHandler:
    """Parses SQL queries and returns the appropriate wire-protocol response bytes.

    Owns current_db state so the Protocol layer doesn't need to track it.
    """

    def __init__(self):
        self.current_db = ""

    def set_db(self, db: str):
        self.current_db = db.lower()

    # ── Public entry point ────────────────────────────────────────────────────

    def handle(self, query: str, seq: int) -> bytes:
        q   = query.strip().upper()
        raw = query.strip()

        # USE db — updates state and returns OK
        m = re.match(r'USE\s+[`"]?(\w+)[`"]?\s*;?$', raw, re.IGNORECASE)
        if m:
            self.current_db = m.group(1).lower()
            return ok_packet(seq)

        if "@@VERSION_COMMENT" in q or "@@VERSION" in q:
            return result_set(seq, ["@@version_comment"], [["MySQL Community Server - GPL"]])

        if q in ("SELECT 1", "SELECT 1;"):
            return result_set(seq, ["1"], [["1"]])

        if "DATABASE()" in q:
            return result_set(seq, ["DATABASE()"], [[self.current_db or ""]])

        if "USER()" in q or "CURRENT_USER()" in q:
            return result_set(seq, ["USER()"], [["root@localhost"]])

        if q.startswith("SHOW DATABASES"):
            return self._show_databases(seq)

        if q.startswith("SHOW TABLES"):
            return self._show_tables(raw, seq)

        if (re.match(r'SHOW\s+(?:FULL\s+)?COLUMNS\s+(?:FROM|IN)', raw, re.IGNORECASE)
                or q.startswith("DESC ") or q.startswith("DESCRIBE ")):
            return self._show_columns(raw, seq)

        if q.startswith("SHOW VARIABLES") or q.startswith("SHOW STATUS"):
            return result_set(seq, ["Variable_name", "Value"], [])

        if q.startswith("SHOW PROCESSLIST"):
            return result_set(seq, ["Id", "User", "Host", "db", "Command", "Time", "State", "Info"], [])

        if q.startswith("SELECT"):
            return self._select(q, raw, seq)

        if q.startswith(("EXPLAIN", "SHOW")):
            return result_set(seq, ["result"], [])

        return ok_packet(seq)

    # ── SHOW handlers ─────────────────────────────────────────────────────────

    def _show_databases(self, seq: int) -> bytes:
        return result_set(seq, ["Database"], [
            ["information_schema"], ["mysql"], [DECOY_DB], ["performance_schema"], ["sys"],
        ])

    def _show_tables(self, raw: str, seq: int) -> bytes:
        in_decoy = self._in_decoy() or bool(
            re.search(r'(?:FROM|IN)\s+[`"]?' + DECOY_DB + r'[`"]?', raw, re.IGNORECASE)
        )
        if in_decoy:
            return result_set(seq, [f"Tables_in_{DECOY_DB}"], [[t] for t in DECOY_DATA])
        return result_set(seq, ["Tables_in_mysql"], [])

    def _show_columns(self, raw: str, seq: int) -> bytes:
        tbl = self._table_from_query(raw)
        if self._in_decoy() and tbl in DECOY_DATA:
            rows = [[c, "varchar(255)", "YES", "", None, ""] for c in DECOY_DATA[tbl]["columns"]]
            return result_set(seq, ["Field", "Type", "Null", "Key", "Default", "Extra"], rows)
        return result_set(seq, ["Field", "Type", "Null", "Key", "Default", "Extra"], [])

    # ── SELECT handler ────────────────────────────────────────────────────────

    def _select(self, q: str, raw: str, seq: int) -> bytes:
        # information_schema introspection for GUI tools
        if "INFORMATION_SCHEMA" in q and "TABLES" in q and DECOY_DB.upper() in q:
            rows = [[DECOY_DB, t, "BASE TABLE"] for t in DECOY_DATA]
            return result_set(seq, ["TABLE_SCHEMA", "TABLE_NAME", "TABLE_TYPE"], rows)

        if "INFORMATION_SCHEMA" in q and "COLUMNS" in q and DECOY_DB.upper() in q:
            rows = []
            for tbl, data in DECOY_DATA.items():
                for i, col in enumerate(data["columns"], 1):
                    rows.append([DECOY_DB, tbl, col, str(i), "varchar", "255"])
            return result_set(seq, [
                "TABLE_SCHEMA", "TABLE_NAME", "COLUMN_NAME",
                "ORDINAL_POSITION", "DATA_TYPE", "CHARACTER_MAXIMUM_LENGTH",
            ], rows)

        tbl = self._table_from_query(raw)
        if self._in_decoy() and tbl in DECOY_DATA:
            return self._select_from_decoy(q, tbl, seq)

        return result_set(seq, ["result"], [])

    def _select_from_decoy(self, q: str, tbl: str, seq: int) -> bytes:
        data = DECOY_DATA[tbl]
        if "COUNT(" in q:
            return result_set(seq, ["COUNT(*)"], [[str(len(data["rows"]))]])
        rows = data["rows"]
        m = re.search(r'\bLIMIT\s+(\d+)', q)
        if m:
            rows = rows[:int(m.group(1))]
        return result_set(seq, data["columns"], rows)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _in_decoy(self) -> bool:
        return self.current_db == DECOY_DB

    def _table_from_query(self, query: str) -> str:
        """Return lowercase table name from FROM clause, DESC, or SHOW COLUMNS."""
        m = re.search(r'\bFROM\s+[`"]?(\w+)[`"]?', query, re.IGNORECASE)
        if m:
            return m.group(1).lower()
        m = re.match(
            r'(?:DESC(?:RIBE)?|SHOW\s+(?:FULL\s+)?COLUMNS\s+(?:FROM|IN))\s+[`"]?(\w+)[`"]?',
            query, re.IGNORECASE,
        )
        if m:
            return m.group(1).lower()
        return ""

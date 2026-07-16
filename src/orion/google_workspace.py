"""Bounded Google Drive, Sheets, Docs, and Slides adapter for ORION."""

from __future__ import annotations

import os
import time
from typing import Any

import requests


API_TIMEOUT = 30
SCOPES = (
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/presentations",
)


def _credentials_error() -> dict:
    return {
        "ok": False,
        "error_code": "google_authorization_required",
        "requires_user": True,
        "error": "Google Workspace is not authorized yet.",
        "recovery": "Add GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_REFRESH_TOKEN with Drive, Sheets, Docs, and Slides access.",
        "required_scopes": list(SCOPES),
    }


def access_token() -> str:
    direct = os.getenv("GOOGLE_ACCESS_TOKEN", "").strip()
    if direct:
        return direct
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN", "").strip()
    if not all((client_id, client_secret, refresh_token)):
        return ""
    response = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=API_TIMEOUT,
    )
    response.raise_for_status()
    return str(response.json().get("access_token", ""))


def _request(method: str, url: str, *, payload: dict | None = None, params: dict | None = None) -> dict:
    token = access_token()
    if not token:
        return _credentials_error()
    response = requests.request(
        method, url, json=payload, params=params,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=API_TIMEOUT,
    )
    if response.status_code in {401, 403}:
        return {
            **_credentials_error(),
            "error": "Google rejected the saved authorization or required scopes.",
            "provider_status": response.status_code,
        }
    response.raise_for_status()
    return {"ok": True, "data": response.json() if response.content else {}}


def search_drive(query: str, limit: int = 20) -> dict:
    escaped = query.replace("'", "\\'")
    result = _request(
        "GET", "https://www.googleapis.com/drive/v3/files",
        params={
            "q": f"trashed = false and name contains '{escaped}'",
            "pageSize": max(1, min(int(limit), 100)),
            "fields": "files(id,name,mimeType,modifiedTime,webViewLink,parents)",
            "orderBy": "modifiedTime desc",
        },
    )
    if not result.get("ok"):
        return result
    return {"ok": True, "files": result["data"].get("files", [])}


def _currency_pattern(currency: str) -> str:
    symbols = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "CAD": "C$", "AUD": "A$"}
    return f'{symbols.get(currency.upper(), currency.upper() + " ")}#,##0.00'


def _budget_values(currency: str) -> list[dict]:
    categories = ["Housing", "Utilities", "Groceries", "Transportation", "Insurance", "Health", "Dining", "Entertainment", "Shopping", "Savings"]
    return [
        {
            "range": "Dashboard!A1:B8",
            "values": [
                ["FINANCIAL DASHBOARD", ""],
                ["Metric", "Value"],
                ["Total Income", '=SUMIF(Transactions!F:F,"Income",Transactions!E:E)'],
                ["Total Expenses", '=SUMIF(Transactions!F:F,"Expense",Transactions!E:E)'],
                ["Net Cash Flow", "=B3-B4"],
                ["Planned Budget", "=SUM(Budget!B2:B)"],
                ["Budget Remaining", "=B6-B4"],
                ["Currency", currency.upper()],
            ],
        },
        {
            "range": "Transactions!A1:G2",
            "values": [
                ["Date", "Description", "Category", "Account", "Amount", "Type", "Notes"],
                ["", "", "", "", "", "Expense", ""],
            ],
        },
        {
            "range": f"Categories!A1:B{len(categories) + 1}",
            "values": [["Category", "Default Type"]] + [[category, "Expense"] for category in categories],
        },
        {
            "range": f"Budget!A1:E{len(categories) + 1}",
            "values": [["Category", "Monthly Budget", "Actual", "Remaining", "% Used"]] + [
                [
                    category, 0,
                    f'=SUMIFS(Transactions!$E:$E,Transactions!$C:$C,$A{row},Transactions!$F:$F,"Expense")',
                    f"=B{row}-C{row}", f"=IFERROR(C{row}/B{row},0)",
                ]
                for row, category in enumerate(categories, start=2)
            ],
        },
    ]


def _sheet_format_requests(sheet_ids: dict[str, int], currency: str) -> list[dict]:
    requests_payload: list[dict] = []
    header_rows = {"Dashboard": 2, "Transactions": 1, "Budget": 1, "Categories": 1}
    for title, frozen_rows in header_rows.items():
        sheet_id = sheet_ids[title]
        requests_payload.extend([
            {"updateSheetProperties": {"properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": frozen_rows}}, "fields": "gridProperties.frozenRowCount"}},
            {"repeatCell": {"range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": frozen_rows}, "cell": {"userEnteredFormat": {"backgroundColor": {"red": 0.04, "green": 0.16, "blue": 0.29}, "textFormat": {"foregroundColor": {"red": 1, "green": 1, "blue": 1}, "bold": True}, "horizontalAlignment": "CENTER"}}, "fields": "userEnteredFormat"}},
            {"autoResizeDimensions": {"dimensions": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 8}}},
        ])
    money = _currency_pattern(currency)
    requests_payload.extend([
        {"repeatCell": {"range": {"sheetId": sheet_ids["Transactions"], "startRowIndex": 1, "startColumnIndex": 4, "endColumnIndex": 5}, "cell": {"userEnteredFormat": {"numberFormat": {"type": "CURRENCY", "pattern": money}}}, "fields": "userEnteredFormat.numberFormat"}},
        {"repeatCell": {"range": {"sheetId": sheet_ids["Budget"], "startRowIndex": 1, "startColumnIndex": 1, "endColumnIndex": 4}, "cell": {"userEnteredFormat": {"numberFormat": {"type": "CURRENCY", "pattern": money}}}, "fields": "userEnteredFormat.numberFormat"}},
        {"repeatCell": {"range": {"sheetId": sheet_ids["Budget"], "startRowIndex": 1, "startColumnIndex": 4, "endColumnIndex": 5}, "cell": {"userEnteredFormat": {"numberFormat": {"type": "PERCENT", "pattern": "0.0%"}}}, "fields": "userEnteredFormat.numberFormat"}},
        {"setDataValidation": {"range": {"sheetId": sheet_ids["Transactions"], "startRowIndex": 1, "startColumnIndex": 2, "endColumnIndex": 3}, "rule": {"condition": {"type": "ONE_OF_RANGE", "values": [{"userEnteredValue": "=Categories!$A$2:$A"}]}, "strict": False, "showCustomUi": True}}},
        {"setDataValidation": {"range": {"sheetId": sheet_ids["Transactions"], "startRowIndex": 1, "startColumnIndex": 5, "endColumnIndex": 6}, "rule": {"condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": "Income"}, {"userEnteredValue": "Expense"}]}, "strict": True, "showCustomUi": True}}},
        {"addChart": {"chart": {"spec": {"title": "Budget vs Actual", "basicChart": {"chartType": "COLUMN", "legendPosition": "BOTTOM_LEGEND", "axis": [{"position": "BOTTOM_AXIS", "title": "Category"}, {"position": "LEFT_AXIS", "title": "Amount"}], "domains": [{"domain": {"sourceRange": {"sources": [{"sheetId": sheet_ids["Budget"], "startRowIndex": 0, "endRowIndex": 11, "startColumnIndex": 0, "endColumnIndex": 1}]}}}], "series": [{"series": {"sourceRange": {"sources": [{"sheetId": sheet_ids["Budget"], "startRowIndex": 0, "endRowIndex": 11, "startColumnIndex": 1, "endColumnIndex": 2}]}}}, {"series": {"sourceRange": {"sources": [{"sheetId": sheet_ids["Budget"], "startRowIndex": 0, "endRowIndex": 11, "startColumnIndex": 2, "endColumnIndex": 3}]}}}]}}, "position": {"overlayPosition": {"anchorCell": {"sheetId": sheet_ids["Dashboard"], "rowIndex": 1, "columnIndex": 3}, "widthPixels": 720, "heightPixels": 420}}}}},
    ])
    return requests_payload


def create_spreadsheet(title: str, template: str = "blank", currency: str = "USD", confirmed: bool = False) -> dict:
    if not confirmed:
        return {"ok": False, "error_code": "confirmation_required", "requires_user": True, "error": "Creating a Drive file requires an explicit request."}
    title = title.strip() or "ORION Spreadsheet"
    template = template.strip().lower()
    sheet_titles = ["Sheet1"] if template == "blank" else ["Dashboard", "Transactions", "Budget", "Categories"]
    created = _request(
        "POST", "https://sheets.googleapis.com/v4/spreadsheets",
        payload={"properties": {"title": title}, "sheets": [{"properties": {"title": name}} for name in sheet_titles]},
    )
    if not created.get("ok"):
        return created
    spreadsheet = created["data"]
    spreadsheet_id = spreadsheet["spreadsheetId"]
    if template in {"budget", "finance", "finances", "expense_tracker"}:
        values = _request(
            "POST", f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values:batchUpdate",
            payload={"valueInputOption": "USER_ENTERED", "data": _budget_values(currency)},
        )
        if not values.get("ok"):
            return {**values, "spreadsheet_id": spreadsheet_id, "partially_created": True}
        sheet_ids = {sheet["properties"]["title"]: sheet["properties"]["sheetId"] for sheet in spreadsheet["sheets"]}
        formatted = _request(
            "POST", f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}:batchUpdate",
            payload={"requests": _sheet_format_requests(sheet_ids, currency)},
        )
        if not formatted.get("ok"):
            return {**formatted, "spreadsheet_id": spreadsheet_id, "partially_created": True}
    return {
        "ok": True, "spreadsheet_id": spreadsheet_id, "title": title, "template": template,
        "url": spreadsheet.get("spreadsheetUrl", f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"),
        "sheets": sheet_titles,
        "verified": True,
    }


def create_document(title: str, content: str, confirmed: bool = False) -> dict:
    if not confirmed:
        return {"ok": False, "error_code": "confirmation_required", "requires_user": True, "error": "Creating a Drive document requires an explicit request."}
    created = _request("POST", "https://docs.googleapis.com/v1/documents", payload={"title": title.strip() or "ORION Document"})
    if not created.get("ok"):
        return created
    document_id = created["data"]["documentId"]
    if content.strip():
        updated = _request(
            "POST", f"https://docs.googleapis.com/v1/documents/{document_id}:batchUpdate",
            payload={"requests": [{"insertText": {"location": {"index": 1}, "text": content}}]},
        )
        if not updated.get("ok"):
            return {**updated, "document_id": document_id, "partially_created": True}
    return {"ok": True, "document_id": document_id, "title": title, "url": f"https://docs.google.com/document/d/{document_id}/edit", "verified": True}


def create_presentation(title: str, confirmed: bool = False) -> dict:
    if not confirmed:
        return {"ok": False, "error_code": "confirmation_required", "requires_user": True, "error": "Creating a Drive presentation requires an explicit request."}
    created = _request("POST", "https://slides.googleapis.com/v1/presentations", payload={"title": title.strip() or "ORION Presentation"})
    if not created.get("ok"):
        return created
    presentation_id = created["data"]["presentationId"]
    return {"ok": True, "presentation_id": presentation_id, "title": title, "url": f"https://docs.google.com/presentation/d/{presentation_id}/edit", "verified": True}

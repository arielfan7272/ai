#!/usr/bin/env python3
"""Fetch Gmail messages received in a date range and save them as JSON."""

from __future__ import annotations

import argparse
import base64
import json
import os
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date '{value}'. Use YYYY-MM-DD."
        ) from exc


def build_query(start_date: date, end_date: date) -> str:
    """Build an inclusive Gmail search query for the given date range."""
    if start_date > end_date:
        raise ValueError("start-date must be on or before end-date")

    after = (start_date - timedelta(days=1)).strftime("%Y/%m/%d")
    before = (end_date + timedelta(days=1)).strftime("%Y/%m/%d")
    return f"after:{after} before:{before}"


def get_gmail_service(credentials_path: Path, token_path: Path):
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not credentials_path.exists():
                raise FileNotFoundError(
                    f"Missing OAuth credentials at {credentials_path}. "
                    "Download credentials.json from Google Cloud Console "
                    "(Gmail API enabled, OAuth desktop client)."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(credentials_path), SCOPES
            )
            creds = flow.run_local_server(port=0)

        token_path.write_text(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def header_value(headers: list[dict], name: str) -> str | None:
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value")
    return None


def decode_body(data: str) -> str:
    raw = base64.urlsafe_b64decode(data + "==")
    return raw.decode("utf-8", errors="replace")


def extract_bodies(payload: dict) -> tuple[str | None, str | None]:
    text_body = None
    html_body = None

    def walk(part: dict) -> None:
        nonlocal text_body, html_body
        mime_type = part.get("mimeType", "")
        body = part.get("body", {})
        data = body.get("data")

        if data:
            decoded = decode_body(data)
            if mime_type == "text/plain" and text_body is None:
                text_body = decoded
            elif mime_type == "text/html" and html_body is None:
                html_body = decoded

        for child in part.get("parts", []):
            walk(child)

    walk(payload)
    return text_body, html_body


def parse_internal_date(internal_date_ms: str | None) -> str | None:
    if not internal_date_ms:
        return None
    timestamp = int(internal_date_ms) / 1000
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def parse_header_date(date_header: str | None) -> str | None:
    if not date_header:
        return None
    try:
        return parsedate_to_datetime(date_header).isoformat()
    except (TypeError, ValueError, OverflowError):
        return date_header


def message_to_dict(message: dict) -> dict:
    payload = message.get("payload", {})
    headers = payload.get("headers", [])
    text_body, html_body = extract_bodies(payload)

    return {
        "id": message.get("id"),
        "thread_id": message.get("threadId"),
        "label_ids": message.get("labelIds", []),
        "snippet": message.get("snippet"),
        "subject": header_value(headers, "Subject"),
        "from": header_value(headers, "From"),
        "to": header_value(headers, "To"),
        "cc": header_value(headers, "Cc"),
        "date": parse_header_date(header_value(headers, "Date")),
        "internal_date": parse_internal_date(message.get("internalDate")),
        "body_text": text_body,
        "body_html": html_body,
    }


def list_message_ids(service, query: str) -> list[str]:
    message_ids: list[str] = []
    page_token = None

    while True:
        response = (
            service.users()
            .messages()
            .list(userId="me", q=query, pageToken=page_token, maxResults=500)
            .execute()
        )
        for item in response.get("messages", []):
            message_ids.append(item["id"])

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return message_ids


def fetch_messages(service, message_ids: list[str]) -> list[dict]:
    emails = []
    for message_id in message_ids:
        message = (
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        emails.append(message_to_dict(message))
    return emails


def default_output_path(start_date: date, end_date: date) -> Path:
    return Path(f"emails_{start_date}_{end_date}.json")


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Fetch Gmail messages received in a date range and save as JSON."
    )
    parser.add_argument(
        "--start-date",
        type=parse_date,
        required=True,
        help="Inclusive start date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--end-date",
        type=parse_date,
        required=True,
        help="Inclusive end date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output JSON file path (default: emails_<start>_<end>.json).",
    )
    parser.add_argument(
        "--query",
        help="Additional Gmail search terms to AND with the date filter.",
    )
    args = parser.parse_args()

    credentials_path = Path(
        os.getenv("GMAIL_CREDENTIALS_PATH", "credentials.json")
    )
    token_path = Path(os.getenv("GMAIL_TOKEN_PATH", "token.json"))
    output_path = args.output or default_output_path(
        args.start_date, args.end_date
    )

    query = build_query(args.start_date, args.end_date)
    if args.query:
        query = f"{query} {args.query.strip()}"

    service = get_gmail_service(credentials_path, token_path)
    message_ids = list_message_ids(service, query)
    emails = fetch_messages(service, message_ids)

    result = {
        "query": query,
        "start_date": args.start_date.isoformat(),
        "end_date": args.end_date.isoformat(),
        "count": len(emails),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "emails": emails,
    }

    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"Saved {len(emails)} emails to {output_path}")


if __name__ == "__main__":
    main()

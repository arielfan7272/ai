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

DOUBAO_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DOUBAO_PRO_MODEL = "doubao-seed-2-0-pro-260215"
DOUBAO_LITE_MODEL = "doubao-seed-2-0-lite-260215"

EMAIL_CATEGORY_INSTRUCTIONS = (
    "这是一个邮件，根据邮件主题分类，如果邮件主题中带有Project，根据Project名称分类，"
    "如果没有project这个名词，但同样有其他带有Project后面的名词的主题的邮件，"
    "也和Project后面名词分为同一类。比如有Project A、Project B和Project C的邮件，"
    "根据project后面的A、B、C分为3类；如果另外有一封邮件主题没有project,但是有A, B, and C，"
    "也分别和Project A、Project B、Project C分为同一类。其他没cover的邮件，分类为其他"
)


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


def get_doubao_response(model_name, prompt):
    """Call Doubao through the OpenAI-compatible Ark endpoint."""
    api_key = os.getenv("ARK_API_KEY")
    if not api_key:
        raise RuntimeError("ARK_API_KEY is not set.")

    from openai import OpenAI

    client = OpenAI(
        base_url=DOUBAO_BASE_URL,
        api_key=api_key,
    )
    response = client.responses.create(
        model=model_name,
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": prompt,
                    },
                ],
            }
        ],
    )
    return response.output_text


def load_emails_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "emails" not in data:
        raise ValueError(f"Missing 'emails' key in {path}")
    return data


def build_category_prompt(email: dict, all_subjects: list[str]) -> str:
    subject_lines = "\n".join(
        f"{index}. {subject}" for index, subject in enumerate(all_subjects, start=1)
    )
    return (
        f"{EMAIL_CATEGORY_INSTRUCTIONS}\n\n"
        f"本批次所有邮件主题：\n{subject_lines}\n\n"
        f"当前邮件：\n"
        f"- id: {email.get('id')}\n"
        f"- subject: {email.get('subject')}\n"
        f"- from: {email.get('from')}\n"
        f"- snippet: {email.get('snippet')}\n\n"
        f"请只返回分类名称，不要返回其他内容。例如：Project A、Project B、其他"
    )


def parse_category(raw: str) -> str:
    category = raw.strip().strip("\"'")
    return category or "其他"


def default_categorized_output_path(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}_categorized.json")


def categorize_emails_from_json(
    input_path: Path,
    output_path: Path | None = None,
    model_name: str = DOUBAO_LITE_MODEL,
) -> dict:
    load_dotenv()
    data = load_emails_json(input_path)
    emails = data["emails"]
    all_subjects = [
        subject for email in emails if (subject := email.get("subject"))
    ]
    total = len(emails)

    for index, email in enumerate(emails, start=1):
        prompt = build_category_prompt(email, all_subjects)
        raw_category = get_doubao_response(model_name, prompt)
        email["category"] = parse_category(raw_category)
        subject = email.get("subject") or "(no subject)"
        print(
            f"Categorized {index}/{total}: {email['category']} - {subject}"
        )

    result = {
        **data,
        "categorized_at": datetime.now(timezone.utc).isoformat(),
        "model": model_name,
        "emails": emails,
    }

    out_path = output_path or default_categorized_output_path(input_path)
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"Saved categorized emails to {out_path}")
    return result


def run_fetch(args: argparse.Namespace) -> None:
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


def run_categorize(args: argparse.Namespace) -> None:
    categorize_emails_from_json(
        input_path=args.input,
        output_path=args.output,
        model_name=args.model,
    )


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Fetch Gmail messages or categorize saved email JSON."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch_parser = subparsers.add_parser(
        "fetch", help="Fetch Gmail messages and save as JSON."
    )
    fetch_parser.add_argument(
        "--start-date",
        type=parse_date,
        required=True,
        help="Inclusive start date (YYYY-MM-DD).",
    )
    fetch_parser.add_argument(
        "--end-date",
        type=parse_date,
        required=True,
        help="Inclusive end date (YYYY-MM-DD).",
    )
    fetch_parser.add_argument(
        "--output",
        type=Path,
        help="Output JSON file path (default: emails_<start>_<end>.json).",
    )
    fetch_parser.add_argument(
        "--query",
        help="Additional Gmail search terms to AND with the date filter.",
    )
    fetch_parser.set_defaults(func=run_fetch)

    categorize_parser = subparsers.add_parser(
        "categorize", help="Categorize emails in a saved JSON file with Doubao."
    )
    categorize_parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Input email JSON file path.",
    )
    categorize_parser.add_argument(
        "--output",
        type=Path,
        help="Output JSON file path (default: <input>_categorized.json).",
    )
    categorize_parser.add_argument(
        "--model",
        default=DOUBAO_LITE_MODEL,
        help=f"Doubao model name (default: {DOUBAO_LITE_MODEL}).",
    )
    categorize_parser.set_defaults(func=run_categorize)

    args = parser.parse_args()
    args.func(args)



# python3 fetch_gmail.py fetch --start-date 2026-06-06 --end-date 2026-06-07
# python3 fetch_gmail.py categorize --input emails_2026-06-06_2026-06-07.json
if __name__ == "__main__":
    main()

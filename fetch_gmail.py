#!/usr/bin/env python3
"""Fetch Gmail messages received in a date range and save them as JSON."""

from __future__ import annotations

import argparse
import base64
import json
import os
import socket
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


def _prefer_ipv4_for_google_api() -> None:
    """Prefer IPv4; httplib2 does not fall back when IPv6 routes are broken."""
    original_getaddrinfo = socket.getaddrinfo

    def getaddrinfo_ipv4_first(
        host, port, family=0, type=0, proto=0, flags=0
    ):
        results = original_getaddrinfo(host, port, family, type, proto, flags)
        return sorted(results, key=lambda item: item[0] != socket.AF_INET)

    socket.getaddrinfo = getaddrinfo_ipv4_first


_prefer_ipv4_for_google_api()

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

EMAIL_SUMMARY_INSTRUCTIONS = (
    "这是一个邮件，根据邮件内容提炼一句话的摘要，并注明是否有附件。"
)

TODO_LIST_GENERATOR_PROMPTS = {
    "cn": (
        "根据邮件内容生成一个 to do list，按项目名称分组，列出需要处理的事项。"
        "项目名称与待办事项请使用中文。"
        "只输出 JSON，不要输出其他解释性文字。格式如下：\n"
        '{"projects": [{"name": "项目名称", "items": [{"text": "需要处理的事项", "done": false}]}]}'
    ),
    "en": (
        "Based on the emails below, generate a to-do list grouped by project name. "
        "Use English for project names and to-do item texts. "
        "Output JSON only, with no other explanatory text. Format:\n"
        '{"projects": [{"name": "Project name", "items": [{"text": "Action item", "done": false}]}]}'
    ),
}

# Backward-compatible alias for existing callers / docs.
TODO_LIST_GENERATOR_PROMPT = TODO_LIST_GENERATOR_PROMPTS["cn"]

EXCLUDED_TODO_CATEGORIES = {"其他", "Other", "other"}


def normalize_todo_lang(lang: str | None) -> str:
    if lang and lang.lower() in TODO_LIST_GENERATOR_PROMPTS:
        return lang.lower()
    return "cn"


def parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date '{value}'. Use YYYY-MM-DD."
        ) from exc


GMAIL_HTTP_TIMEOUT = 60
COMMON_LOCAL_PROXY_PORTS = (7890, 7897, 10809, 1080)


def resolve_proxy_url() -> str | None:
    for key in (
        "GMAIL_PROXY",
        "HTTPS_PROXY",
        "https_proxy",
        "HTTP_PROXY",
        "http_proxy",
        "ALL_PROXY",
        "all_proxy",
    ):
        value = os.getenv(key)
        if value:
            return value.strip()
    return None


def detect_local_proxy_url() -> str | None:
    for port in COMMON_LOCAL_PROXY_PORTS:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return f"http://127.0.0.1:{port}"
        except OSError:
            continue
    return None


def configure_gmail_proxy() -> str | None:
    """Configure proxy for Gmail API calls (httplib2 needs PySocks for HTTPS)."""
    proxy_url = resolve_proxy_url() or detect_local_proxy_url()
    if not proxy_url:
        return None

    os.environ.setdefault("HTTPS_PROXY", proxy_url)
    os.environ.setdefault("HTTP_PROXY", proxy_url)
    print(f"Using proxy for Gmail API: {proxy_url}")
    return proxy_url


def build_authorized_gmail_http(creds, proxy_url: str | None):
    import httplib2
    from google_auth_httplib2 import AuthorizedHttp

    if proxy_url:
        http = httplib2.Http(
            proxy_info=httplib2.proxy_info_from_url(proxy_url),
            timeout=GMAIL_HTTP_TIMEOUT,
        )
    else:
        http = httplib2.Http(timeout=GMAIL_HTTP_TIMEOUT)

    return AuthorizedHttp(creds, http=http)


def build_query(start_date: date, end_date: date) -> str:
    """Build an inclusive Gmail search query for the given date range."""
    if start_date > end_date:
        raise ValueError("start-date must be on or before end-date")

    after = (start_date - timedelta(days=1)).strftime("%Y/%m/%d")
    before = (end_date + timedelta(days=1)).strftime("%Y/%m/%d")
    return f"after:{after} before:{before}"


def get_gmail_service(credentials_path: Path, token_path: Path):
    from google.auth.exceptions import RefreshError

    proxy_url = configure_gmail_proxy()
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                print(
                    "Saved Gmail token is invalid or revoked. "
                    "Opening browser to re-authorize..."
                )
                creds = None

        if not creds or not creds.valid:
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

        token_path.write_text(creds.to_json(), encoding="utf-8")

    authorized_http = build_authorized_gmail_http(creds, proxy_url)
    return build("gmail", "v1", http=authorized_http)


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


EMAIL_BODY_MAX_CHARS = 4000


def get_email_body(email: dict, max_chars: int = EMAIL_BODY_MAX_CHARS) -> str:
    body = email.get("body_text") or email.get("snippet") or ""
    if len(body) > max_chars:
        body = body[:max_chars] + "…"
    return body


def build_summary_prompt(email: dict) -> str:
    body = get_email_body(email)
    return (
        f"{EMAIL_SUMMARY_INSTRUCTIONS}\n\n"
        f"当前邮件：\n"
        f"- id: {email.get('id')}\n"
        f"- subject: {email.get('subject')}\n"
        f"- from: {email.get('from')}\n"
        f"- date: {email.get('date')}\n"
        f"- body:\n{body}\n\n"
        f"请只返回一句话摘要（含是否有附件），不要返回其他内容。"
    )


def parse_summary(raw: str) -> str:
    return raw.strip().strip("\"'")


def default_summarized_output_path(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}_summarized.json")


def default_processed_output_path(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}_processed.json")


def default_todo_output_path(input_path: Path) -> Path:
    stem = input_path.stem.removesuffix("_processed")
    return input_path.with_name(f"{stem}_todo.json")


def parse_todo_response(raw: str) -> dict:
    text = raw.strip().strip("\"'")
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    data = json.loads(text)
    if "projects" not in data:
        raise ValueError("Todo response must contain a 'projects' key.")
    return data


def build_todo_prompt(emails: list[dict], lang: str = "cn") -> str:
    lang = normalize_todo_lang(lang)
    instruction = TODO_LIST_GENERATOR_PROMPTS[lang]
    lines = []
    if lang == "en":
        for index, email in enumerate(emails, start=1):
            lines.append(
                f"{index}. Project: {email.get('category')}\n"
                f"   Subject: {email.get('subject')}\n"
                f"   From: {email.get('from')}\n"
                f"   Date: {email.get('date')}\n"
                f"   Body:\n{get_email_body(email)}"
            )
        email_block = "\n\n".join(lines)
        return f"{instruction}\n\nEmail list:\n{email_block}"

    for index, email in enumerate(emails, start=1):
        lines.append(
            f"{index}. 项目: {email.get('category')}\n"
            f"   主题: {email.get('subject')}\n"
            f"   发件人: {email.get('from')}\n"
            f"   日期: {email.get('date')}\n"
            f"   正文:\n{get_email_body(email)}"
        )
    email_block = "\n\n".join(lines)
    return f"{instruction}\n\n邮件列表：\n{email_block}"


def generate_todo_from_json(
    input_path: Path,
    output_path: Path | None = None,
    model_name: str = DOUBAO_PRO_MODEL,
    lang: str = "cn",
) -> dict:
    load_dotenv()
    lang = normalize_todo_lang(lang)
    data = load_emails_json(input_path)
    emails = data["emails"]

    missing_category = [
        email.get("id") or "(unknown id)"
        for email in emails
        if "category" not in email
    ]
    if missing_category:
        raise ValueError(
            f"Input must be processed JSON with category. "
            f"Missing category for email ids: {', '.join(missing_category)}"
        )

    missing_body = [
        email.get("id") or "(unknown id)"
        for email in emails
        if not (email.get("body_text") or email.get("snippet"))
    ]
    if missing_body:
        raise ValueError(
            f"Input must include original email body (body_text or snippet). "
            f"Missing body for email ids: {', '.join(missing_body)}"
        )

    actionable = [
        email
        for email in emails
        if email.get("category") not in EXCLUDED_TODO_CATEGORIES
    ]
    skipped = len(emails) - len(actionable)
    if skipped:
        print(f"Skipped {skipped} email(s) in excluded categories")

    if not actionable:
        print("No actionable emails to include in todo list.")
        result = {
            "source": str(input_path),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model": model_name,
            "lang": lang,
            "projects": [],
        }
        out_path = output_path or default_todo_output_path(input_path)
        out_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"Saved todo list to {out_path}")
        return result

    print(f"Generating todo list ({lang}) from {len(actionable)} email(s)...")
    prompt = build_todo_prompt(actionable, lang=lang)
    raw_todo = get_doubao_response(model_name, prompt)
    todo_data = parse_todo_response(raw_todo)

    result = {
        "source": str(input_path),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": model_name,
        "lang": lang,
        **todo_data,
    }

    out_path = output_path or default_todo_output_path(input_path)
    out_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Saved todo list to {out_path}")
    return result


class EmptyInboxError(RuntimeError):
    """Raised when Gmail returns no messages for the requested date."""


def generate_todo_from_gmail_date(
    work_date: date,
    lang: str = "en",
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    emails_dir: Path | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> dict:
    """Fetch → process → todo for a date range; return todo document with projects.

    ``work_date`` is the tracker day receiving the merge. Emails are fetched for
    ``start_date``..``end_date`` (inclusive), defaulting both to ``work_date``.
    """
    load_dotenv()
    lang = normalize_todo_lang(lang)
    progress: Callable[[str], None] = on_progress or (lambda _step: None)

    range_start = start_date or work_date
    range_end = end_date or work_date
    if range_start > range_end:
        raise ValueError("start_date must be on or before end_date")

    out_dir = emails_dir or Path(".time_logs") / "emails"
    out_dir.mkdir(parents=True, exist_ok=True)
    fetch_path = (
        out_dir
        / f"emails_{range_start.isoformat()}_{range_end.isoformat()}.json"
    )
    processed_path = default_processed_output_path(fetch_path)
    todo_path = default_todo_output_path(processed_path)

    progress("fetch")
    credentials_path = Path(
        os.getenv("GMAIL_CREDENTIALS_PATH", "credentials.json")
    )
    token_path = Path(os.getenv("GMAIL_TOKEN_PATH", "token.json"))
    query = build_query(range_start, range_end)
    service = get_gmail_service(credentials_path, token_path)
    message_ids = list_message_ids(service, query)
    emails = fetch_messages(service, message_ids)

    fetch_result = {
        "query": query,
        "start_date": range_start.isoformat(),
        "end_date": range_end.isoformat(),
        "count": len(emails),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "emails": emails,
    }
    fetch_path.write_text(
        json.dumps(fetch_result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    if not emails:
        if range_start == range_end:
            range_label = range_start.isoformat()
        else:
            range_label = f"{range_start.isoformat()}..{range_end.isoformat()}"
        raise EmptyInboxError(f"No emails found for {range_label}.")

    progress("process")
    process_emails_from_json(
        input_path=fetch_path,
        output_path=processed_path,
    )

    progress("generate")
    return generate_todo_from_json(
        input_path=processed_path,
        output_path=todo_path,
        lang=lang,
    )


def summarize_emails_from_json(
    input_path: Path,
    output_path: Path | None = None,
    model_name: str = DOUBAO_LITE_MODEL,
) -> dict:
    load_dotenv()
    data = load_emails_json(input_path)
    emails = data["emails"]
    total = len(emails)

    for index, email in enumerate(emails, start=1):
        prompt = build_summary_prompt(email)
        raw_summary = get_doubao_response(model_name, prompt)
        email["summary"] = parse_summary(raw_summary)
        subject = email.get("subject") or "(no subject)"
        print(f"Summarized {index}/{total}: {subject}")

    result = {
        **data,
        "summarized_at": datetime.now(timezone.utc).isoformat(),
        "model": model_name,
        "emails": emails,
    }

    out_path = output_path or default_summarized_output_path(input_path)
    out_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Saved summarized emails to {out_path}")
    return result


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
    out_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Saved categorized emails to {out_path}")
    return result


def process_emails_from_json(
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
        category_prompt = build_category_prompt(email, all_subjects)
        raw_category = get_doubao_response(model_name, category_prompt)
        email["category"] = parse_category(raw_category)

        summary_prompt = build_summary_prompt(email)
        raw_summary = get_doubao_response(model_name, summary_prompt)
        email["summary"] = parse_summary(raw_summary)

        subject = email.get("subject") or "(no subject)"
        print(
            f"Processed {index}/{total}: {email['category']} - {subject}"
        )

    result = {
        **data,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "model": model_name,
        "emails": emails,
    }

    out_path = output_path or default_processed_output_path(input_path)
    out_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Saved processed emails to {out_path}")
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

    output_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Saved {len(emails)} emails to {output_path}")


def run_categorize(args: argparse.Namespace) -> None:
    categorize_emails_from_json(
        input_path=args.input,
        output_path=args.output,
        model_name=args.model,
    )


def run_summarize(args: argparse.Namespace) -> None:
    summarize_emails_from_json(
        input_path=args.input,
        output_path=args.output,
        model_name=args.model,
    )


def run_process(args: argparse.Namespace) -> None:
    process_emails_from_json(
        input_path=args.input,
        output_path=args.output,
        model_name=args.model,
    )


def run_todo(args: argparse.Namespace) -> None:
    generate_todo_from_json(
        input_path=args.input,
        output_path=args.output,
        model_name=args.model,
        lang=args.lang,
    )


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description=(
            "Fetch Gmail messages, or categorize, summarize, process, "
            "or generate a todo list from saved email JSON."
        )
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

    summarize_parser = subparsers.add_parser(
        "summarize", help="Summarize emails in a saved JSON file with Doubao."
    )
    summarize_parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Input email JSON file path.",
    )
    summarize_parser.add_argument(
        "--output",
        type=Path,
        help="Output JSON file path (default: <input>_summarized.json).",
    )
    summarize_parser.add_argument(
        "--model",
        default=DOUBAO_LITE_MODEL,
        help=f"Doubao model name (default: {DOUBAO_LITE_MODEL}).",
    )
    summarize_parser.set_defaults(func=run_summarize)

    process_parser = subparsers.add_parser(
        "process",
        help=(
            "Categorize and summarize emails in a saved JSON file "
            "with Doubao."
        ),
    )
    process_parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Input email JSON file path.",
    )
    process_parser.add_argument(
        "--output",
        type=Path,
        help="Output JSON file path (default: <input>_processed.json).",
    )
    process_parser.add_argument(
        "--model",
        default=DOUBAO_LITE_MODEL,
        help=f"Doubao model name (default: {DOUBAO_LITE_MODEL}).",
    )
    process_parser.set_defaults(func=run_process)

    todo_parser = subparsers.add_parser(
        "todo",
        help=(
            "Generate an editable JSON todo list from processed email JSON "
            "with Doubao."
        ),
    )
    todo_parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Input processed email JSON file path.",
    )
    todo_parser.add_argument(
        "--output",
        type=Path,
        help="Output JSON file path (default: <input>_todo.json).",
    )
    todo_parser.add_argument(
        "--model",
        default=DOUBAO_PRO_MODEL,
        help=f"Doubao model name (default: {DOUBAO_PRO_MODEL}).",
    )
    todo_parser.add_argument(
        "--lang",
        choices=["en", "cn"],
        default="cn",
        help="Language for generated todo items (default: cn).",
    )
    todo_parser.set_defaults(func=run_todo)

    args = parser.parse_args()
    args.func(args)



# python3 fetch_gmail.py fetch --start-date 2026-06-06 --end-date 2026-06-07
# python3 fetch_gmail.py process --input emails_2026-06-06_2026-06-07.json
# python3 fetch_gmail.py todo --input emails_2026-06-06_2026-06-07_processed.json
# python3 time_tracker.py
if __name__ == "__main__":
    main()

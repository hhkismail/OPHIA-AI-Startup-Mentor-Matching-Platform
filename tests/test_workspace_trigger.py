"""Google Workspace automation against fake Gmail / Drive / Calendar services."""

import base64
import email
from unittest.mock import MagicMock

import pytest

import workspace_trigger as wt


@pytest.fixture
def google(monkeypatch):
    svc = MagicMock()
    svc.files().create().execute.return_value = {"id": "F1", "webViewLink": "https://drive/F1"}
    svc.events().insert().execute.return_value = {
        "id": "EV1", "conferenceData": {"entryPoints": [{"uri": "https://meet/x"}]}}
    monkeypatch.setattr(wt, "build", lambda *a, **k: svc)
    monkeypatch.setattr(wt, "get_google_credentials", lambda: object())
    monkeypatch.setattr(wt, "SENDER_EMAIL", "admin@example.com")
    return svc


def run(**kw):
    args = dict(startup_name="Data<Shield>", mentor_name="Raza", synergy_score=90,
                contact_email="founder@example.com")
    return wt.trigger_workspace_automation(**{**args, **kw})


def test_all_three_steps_succeed(google):
    r = run()
    assert r["email_sent"] is True
    assert r["drive_folder_url"] == "https://drive/F1"
    assert r["calendar_event_id"] == "EV1"


def test_email_html_escapes_names(google):
    run()
    raw = google.users().messages().send.call_args.kwargs["body"]["raw"]
    html = email.message_from_bytes(base64.urlsafe_b64decode(raw)).get_payload()[0].get_payload(decode=True).decode()
    assert "Data&lt;Shield&gt;" in html and "Data<Shield>" not in html


def test_milestone_doc_is_created_with_content(google):
    run()
    media = next(c.kwargs["media_body"] for c in google.files().create.call_args_list
                 if c.kwargs.get("media_body"))
    text = media.getbytes(0, media.size()).decode()
    assert "DAY 30" in text and "Data<Shield>" in text


def test_folder_is_shared_privately_not_public(google):
    run()
    body = google.permissions().create.call_args.kwargs["body"]
    assert body == {"type": "user", "role": "writer", "emailAddress": "founder@example.com"}


def test_folder_not_shared_when_contact_is_the_sender(google):
    run(contact_email="admin@example.com")
    google.permissions().create.assert_not_called()


def test_kickoff_is_10am_kuala_lumpur_time(google):
    run()
    start = google.events().insert.call_args.kwargs["body"]["start"]["dateTime"]
    assert start.endswith("T10:00:00+08:00")


def test_each_kickoff_gets_a_unique_meet_request_id(google):
    run(); run()
    ids = [c.kwargs["body"]["conferenceData"]["createRequest"]["requestId"]
           for c in google.events().insert.call_args_list if c.kwargs]
    assert len(ids) == 2 and ids[0] != ids[1]


def test_no_credentials_stops_before_any_api_call(monkeypatch):
    monkeypatch.setattr(wt, "get_google_credentials", lambda: None)
    monkeypatch.setattr(wt, "build", lambda *a, **k: pytest.fail("no API calls without credentials"))
    assert run()["errors"] == ["Failed to get Google credentials"]


def test_one_failing_step_does_not_stop_the_others(google):
    google.users().messages().send().execute.side_effect = RuntimeError("gmail down")
    r = run()
    assert r["email_sent"] is False
    assert r["drive_folder_url"] and r["calendar_event_id"]


def test_template_has_no_third_party_affiliation():
    text = wt.get_milestone_doc_content("S", "M")
    assert "Cradle" not in text and "{startup_name}" not in text

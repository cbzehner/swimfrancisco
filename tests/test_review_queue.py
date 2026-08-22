from __future__ import annotations

import json
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from schedules.models import PoolEntry
from schedules.publish import PublishRefuse
from schedules.review_server import ReviewApp, make_handler

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
SHA_29797 = "1" * 64
SHA_29796 = "2" * 64
SHA_29797_NEW = "f" * 64
SHA_HAM = "a" * 64
SHA_FALL1 = "c" * 64
SHA_MAY = "d" * 64
SHA_LATER = "e" * 64
BALBOA_29797 = "https://sfrecpark.org/DocumentCenter/View/29797"
BALBOA_29796 = "https://sfrecpark.org/DocumentCenter/View/29796"
SAVA_FALL1 = "https://sfrecpark.org/DocumentCenter/View/29815"
SAVA_FALL2 = "https://sfrecpark.org/DocumentCenter/View/29805"
GARFIELD_29799 = "https://sfrecpark.org/DocumentCenter/View/29799"
GARFIELD_PIN = "https://sfrecpark.org/DocumentCenter/View/29564"


def _payload(*, start: str, end: str, n: int = 5) -> dict:
    return {
        "effective_start": start,
        "effective_end": end,
        "schedule_basis": "swim_schedule",
        "sessions": [
            {
                "day": DAYS[i],
                "type": "lap_swim",
                "start": "07:00",
                "end": "08:00",
                "evidence": "Lap Swim 7-8am",
            }
            for i in range(n)
        ],
        "closures": [],
    }


def _write_capture(
    data: Path,
    slug: str,
    sha: str,
    *,
    fetch_date: str,
    source_pdf_url: str,
    payload: dict | None = None,
    reviewed: bool = False,
) -> Path:
    review_dir = data / slug / f"{fetch_date}-{sha[:12]}"
    review_dir.mkdir(parents=True, exist_ok=True)
    (review_dir / "gemini-model.json").write_text(
        json.dumps(
            {
                "pdf_sha256": sha,
                "source_pdf_url": source_pdf_url,
                "payload": payload or _payload(start="2026-08-18", end="2026-12-12"),
            }
        )
    )
    (review_dir / "source.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    if reviewed:
        (review_dir / "reviewed.json").write_text(
            json.dumps(
                {
                    "slug": slug,
                    "pdf_sha256": sha,
                    "reviewed_at": fetch_date,
                    "source_pdf_url": source_pdf_url,
                    "payload": payload or _payload(start="2026-03-17", end="2026-06-06"),
                }
            )
        )
    return review_dir


def _seed_content(content_dir: Path, slug: str) -> Path:
    path = content_dir / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    sessions = "\n".join(
        (
            "[[extra.schedules.sessions]]\n"
            f'day = "{DAYS[i]}"\n'
            'type = "lap_swim"\n'
            'start = "07:00"\n'
            'end = "08:00"\n'
        )
        for i in range(5)
    )
    path.write_text(
        "+++\n"
        f'title = "{slug}"\n'
        f'slug = "{slug}"\n\n'
        "[extra]\n\n"
        "[[extra.schedules]]\n"
        'effective_start = "2026-03-17"\n'
        'schedule_basis = "swim_schedule"\n'
        'effective_end = "2026-06-06"\n'
        'last_verified_at = "2026-04-19"\n\n'
        f"{sessions}"
        "+++\n"
    )
    return path


def _entry(slug: str, pdf_url: str) -> PoolEntry:
    return PoolEntry(
        slug=slug,
        pdf_url=pdf_url,
        official_page_url=f"https://sfrecpark.org/facilities/{slug}",
        source_kind="sfrecpark_pdf",
        source_status="published",
    )


def _balboa_decision() -> dict:
    return {
        "slug": "balboa-pool",
        "action": "unchanged",
        "blocking": False,
        "kind": "session_grid",
        "reason": "sequential_windows",
        "candidates": [
            {
                "view_id": 29797,
                "href": BALBOA_29797,
                "kind": "session_grid",
                "source": "table",
                "window_start": "2026-08-11",
                "window_end": "2026-08-29",
            },
            {
                "view_id": 29796,
                "href": BALBOA_29796,
                "kind": "session_grid",
                "source": "band",
                "window_start": "2026-08-30",
                "window_end": "2026-12-12",
            },
        ],
    }


def _sava_decision() -> dict:
    return {
        "slug": "sava-pool",
        "action": "unchanged",
        "blocking": False,
        "kind": "session_grid",
        "reason": "sequential_windows",
        "candidates": [
            {
                "view_id": 29815,
                "href": SAVA_FALL1,
                "kind": "session_grid",
                "source": "table",
                "window_start": "2026-08-18",
                "window_end": "2026-08-28",
            },
            {
                "view_id": 29805,
                "href": SAVA_FALL2,
                "kind": "session_grid",
                "source": "band",
                "window_start": "2026-08-29",
                "window_end": "2026-12-12",
            },
        ],
    }


def _write_decisions(tmp_dir: Path, decisions: list[dict]) -> None:
    tmp_dir.mkdir(parents=True, exist_ok=True)
    (tmp_dir / "discovery-decisions.json").write_text(json.dumps(decisions))


def _identities(*pairs: tuple[str, str]):
    mapping = dict(pairs)

    def identity(slug: str, url: str | None = None) -> str:
        if url is not None and url in mapping:
            return mapping[url]
        if slug in mapping:
            return mapping[slug]
        raise AssertionError(f"unexpected source identity slug={slug!r} url={url!r}")

    return identity


@pytest.fixture
def queue_env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    content = tmp_path / "content" / "spots"
    tmp = tmp_path / "tmp"
    data.mkdir()
    content.mkdir(parents=True)
    tmp.mkdir()
    monkeypatch.setattr("schedules.publish.extract_page_texts", lambda _bytes: ["Monday"])
    monkeypatch.setattr("schedules.publish.load_quarantine", lambda: frozenset())
    return data, content, tmp


def _app(data: Path, content: Path, tmp: Path) -> ReviewApp:
    return ReviewApp(data_root=data, content_spots_dir=content, tmp_dir=tmp)


def _serve(app: ReviewApp) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _http_json(server: ThreadingHTTPServer, method: str, path: str, body: dict | None = None):
    conn = HTTPConnection("127.0.0.1", server.server_port)
    raw = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    conn.request(method, path, body=raw, headers=headers)
    response = conn.getresponse()
    payload = json.loads(response.read().decode())
    conn.close()
    return response.status, payload


def _seed_balboa(data: Path) -> None:
    _write_capture(
        data,
        "balboa-pool",
        SHA_29797,
        fetch_date="2026-08-19",
        source_pdf_url=BALBOA_29797,
        payload=_payload(start="2026-08-11", end="2026-08-29"),
    )
    _write_capture(
        data,
        "balboa-pool",
        SHA_29796,
        fetch_date="2026-08-20",
        source_pdf_url=BALBOA_29796,
        payload=_payload(start="2026-08-30", end="2026-12-12"),
    )


def test_save_all_edited_effective_end_lands_in_content(queue_env, monkeypatch):
    data, content, tmp = queue_env
    _seed_balboa(data)
    _seed_content(content, "balboa-pool")
    _write_decisions(tmp, [_balboa_decision()])
    monkeypatch.setattr(
        "schedules.review_server.load_registry",
        lambda: [_entry("balboa-pool", BALBOA_29797)],
    )
    monkeypatch.setattr(
        "schedules.review_server.current_source_identity",
        _identities((BALBOA_29797, SHA_29797), (BALBOA_29796, SHA_29796)),
    )
    app = _app(data, content, tmp)
    first = app.review("balboa-pool", sha12=SHA_29797[:12])
    second = app.review("balboa-pool", sha12=SHA_29796[:12])
    first["envelope"]["payload"]["effective_end"] = "2026-08-28"

    app.save_sequential(
        "balboa-pool",
        {
            SHA_29797[:12]: first["envelope"],
            SHA_29796[:12]: second["envelope"],
        },
    )

    rendered = (content / "balboa-pool.md").read_text()
    assert 'effective_end = "2026-08-28"' in rendered
    assert (data / "balboa-pool" / f"2026-08-19-{SHA_29797[:12]}" / "reviewed.json").exists()
    assert (data / "balboa-pool" / f"2026-08-20-{SHA_29796[:12]}" / "reviewed.json").exists()
    envelope = json.loads(
        (data / "balboa-pool" / f"2026-08-19-{SHA_29797[:12]}" / "reviewed.json").read_text()
    )
    assert envelope["payload"]["effective_end"] == "2026-08-28"
    assert envelope["attested_by"] == "human"


def test_per_card_sequential_post_does_not_write_reviewed_json(queue_env, monkeypatch):
    data, content, tmp = queue_env
    _seed_balboa(data)
    _seed_content(content, "balboa-pool")
    _write_decisions(tmp, [_balboa_decision()])
    monkeypatch.setattr(
        "schedules.review_server.load_registry",
        lambda: [_entry("balboa-pool", BALBOA_29797)],
    )
    monkeypatch.setattr(
        "schedules.review_server.current_source_identity",
        _identities((BALBOA_29797, SHA_29797), (BALBOA_29796, SHA_29796)),
    )
    app = _app(data, content, tmp)
    envelope = app.review("balboa-pool", sha12=SHA_29797[:12])["envelope"]
    server = _serve(app)
    try:
        status, payload = _http_json(
            server,
            "POST",
            f"/api/reviews/balboa-pool/{SHA_29797[:12]}",
            {
                "envelope": envelope,
                "attested": True,
                "source_identity": SHA_29797,
            },
        )
    finally:
        server.shutdown()
        server.server_close()

    assert status == 200
    assert payload == {"ok": True}
    assert not (data / "balboa-pool" / f"2026-08-19-{SHA_29797[:12]}" / "reviewed.json").exists()
    assert not (data / "balboa-pool" / f"2026-08-20-{SHA_29796[:12]}" / "reviewed.json").exists()


def test_hamilton_unique_grid_save_projects_one_dir(queue_env, monkeypatch):
    data, content, tmp = queue_env
    review_dir = _write_capture(
        data,
        "hamilton-pool",
        SHA_HAM,
        fetch_date="2026-08-20",
        source_pdf_url="https://sfrecpark.org/DocumentCenter/View/29800",
        payload=_payload(start="2026-08-18", end="2026-12-12"),
    )
    _seed_content(content, "hamilton-pool")
    monkeypatch.setattr(
        "schedules.review_server.load_registry",
        lambda: [_entry("hamilton-pool", "https://sfrecpark.org/DocumentCenter/View/29800")],
    )
    monkeypatch.setattr(
        "schedules.review_server.current_source_identity",
        lambda slug, url=None: SHA_HAM,
    )
    app = _app(data, content, tmp)
    review = app.review("hamilton-pool")
    assert "payload" not in review["candidate"]
    assert "source_url" not in review["candidate"]
    assert "view_id" not in review["candidate"]
    envelope = review["envelope"]

    result = app.save("hamilton-pool", envelope, SHA_HAM)

    assert result == review_dir / "reviewed.json"
    assert result.exists()
    assert "[[extra.schedules.sessions]]" in (content / "hamilton-pool.md").read_text()
    assert json.loads(result.read_text())["attested_by"] == "human"


def test_unpublished_balboa_ordinary_save_refuses(queue_env, monkeypatch):
    data, content, tmp = queue_env
    _seed_balboa(data)
    _seed_content(content, "balboa-pool")
    _write_decisions(tmp, [_balboa_decision()])
    monkeypatch.setattr(
        "schedules.review_server.load_registry",
        lambda: [_entry("balboa-pool", BALBOA_29797)],
    )
    monkeypatch.setattr(
        "schedules.review_server.current_source_identity",
        _identities((BALBOA_29797, SHA_29797), (BALBOA_29796, SHA_29796)),
    )
    app = _app(data, content, tmp)
    first = app.review("balboa-pool", sha12=SHA_29797[:12])["envelope"]
    second = app.review("balboa-pool", sha12=SHA_29796[:12])["envelope"]
    server = _serve(app)
    try:
        for envelope, sha in ((first, SHA_29797), (second, SHA_29796)):
            status, payload = _http_json(
                server,
                "POST",
                "/api/reviews/balboa-pool",
                {"envelope": envelope, "attested": True, "source_identity": sha},
            )
            assert status == 400
            assert "sequential_incomplete" in payload["error"]
    finally:
        server.shutdown()
        server.server_close()
    assert not (data / "balboa-pool" / f"2026-08-19-{SHA_29797[:12]}" / "reviewed.json").exists()
    assert not (data / "balboa-pool" / f"2026-08-20-{SHA_29796[:12]}" / "reviewed.json").exists()


def test_save_sequential_missing_extracted_sibling_refuses(queue_env, monkeypatch):
    data, content, tmp = queue_env
    _write_capture(
        data,
        "sava-pool",
        SHA_FALL1,
        fetch_date="2026-08-19",
        source_pdf_url=SAVA_FALL1,
        payload=_payload(start="2026-08-18", end="2026-08-28"),
    )
    _seed_content(content, "sava-pool")
    _write_decisions(tmp, [_sava_decision()])
    monkeypatch.setattr(
        "schedules.review_server.load_registry",
        lambda: [_entry("sava-pool", SAVA_FALL1)],
    )
    monkeypatch.setattr(
        "schedules.review_server.current_source_identity",
        _identities((SAVA_FALL1, SHA_FALL1)),
    )
    app = _app(data, content, tmp)
    envelope = app.review("sava-pool", sha12=SHA_FALL1[:12])["envelope"]

    with pytest.raises(PublishRefuse) as exc_info:
        app.save_sequential("sava-pool", {SHA_FALL1[:12]: envelope})
    assert exc_info.value.code == "sequential_incomplete"

    assert not (data / "sava-pool" / f"2026-08-19-{SHA_FALL1[:12]}" / "reviewed.json").exists()


def test_may_leftover_dirs_with_later_reviewed_do_not_appear(queue_env, monkeypatch):
    data, content, tmp = queue_env
    _write_capture(
        data,
        "hamilton-pool",
        SHA_MAY,
        fetch_date="2026-05-17",
        source_pdf_url="https://sfrecpark.org/DocumentCenter/View/29599",
    )
    _write_capture(
        data,
        "hamilton-pool",
        SHA_LATER,
        fetch_date="2026-08-12",
        source_pdf_url="https://sfrecpark.org/DocumentCenter/View/29800",
        reviewed=True,
    )
    monkeypatch.setattr(
        "schedules.review_server.load_registry",
        lambda: [_entry("hamilton-pool", "https://sfrecpark.org/DocumentCenter/View/29800")],
    )
    app = _app(data, content, tmp)

    assert app.list_reviews() == []
    assert app.candidate("hamilton-pool") is None


def test_band_session_grid_not_on_pin_is_hidden(queue_env, monkeypatch):
    data, content, tmp = queue_env
    _write_capture(
        data,
        "garfield-pool",
        SHA_HAM,
        fetch_date="2026-08-20",
        source_pdf_url=GARFIELD_29799,
        payload=_payload(start="2026-09-08", end="2026-12-12"),
    )
    _write_decisions(
        tmp,
        [
            {
                "slug": "garfield-pool",
                "action": "flag",
                "blocking": True,
                "kind": "session_grid",
                "reason": "band_session_grid",
                "candidates": [
                    {
                        "view_id": 29799,
                        "href": GARFIELD_29799,
                        "kind": "session_grid",
                        "source": "band",
                    }
                ],
            }
        ],
    )
    monkeypatch.setattr(
        "schedules.review_server.load_registry",
        lambda: [_entry("garfield-pool", GARFIELD_PIN)],
    )
    app = _app(data, content, tmp)

    assert app.list_reviews() == []


def test_sequential_queue_lists_every_unpublished_sibling(queue_env, monkeypatch):
    data, content, tmp = queue_env
    _seed_balboa(data)
    _write_decisions(tmp, [_balboa_decision()])
    monkeypatch.setattr(
        "schedules.review_server.load_registry",
        lambda: [_entry("balboa-pool", BALBOA_29797)],
    )
    app = _app(data, content, tmp)

    listed = app.list_reviews()
    assert [item["sha12"] for item in listed] == [SHA_29797[:12], SHA_29796[:12]]
    assert all(item["sequential"] is True and item["slug"] == "balboa-pool" for item in listed)


def test_sequential_refresh_keeps_latest_per_view_id_and_save_all_writes_new(
    queue_env, monkeypatch
):
    data, content, tmp = queue_env
    _seed_balboa(data)
    _seed_content(content, "balboa-pool")
    _write_decisions(tmp, [_balboa_decision()])
    monkeypatch.setattr(
        "schedules.review_server.load_registry",
        lambda: [_entry("balboa-pool", BALBOA_29797)],
    )
    monkeypatch.setattr(
        "schedules.review_server.current_source_identity",
        _identities((BALBOA_29797, SHA_29797_NEW), (BALBOA_29796, SHA_29796)),
    )

    def fake_pipeline(_command):
        _write_capture(
            data,
            "balboa-pool",
            SHA_29797_NEW,
            fetch_date="2026-08-21",
            source_pdf_url=BALBOA_29797,
            payload=_payload(start="2026-08-11", end="2026-08-29"),
        )
        return (0, None, [object()])

    monkeypatch.setattr("schedules.review_server.run_pipeline", fake_pipeline)
    app = _app(data, content, tmp)

    refreshed = app.refresh("balboa-pool", sha12=SHA_29797[:12])
    assert refreshed["candidate"]["sha12"] == SHA_29797_NEW[:12]
    listed = {item["sha12"] for item in app.list_reviews()}
    assert listed == {SHA_29797_NEW[:12], SHA_29796[:12]}
    assert app.candidate("balboa-pool", sha12=SHA_29797[:12]) is None

    sibling = app.review("balboa-pool", sha12=SHA_29796[:12])
    app.save_sequential(
        "balboa-pool",
        {
            SHA_29797_NEW[:12]: refreshed["envelope"],
            SHA_29796[:12]: sibling["envelope"],
        },
    )

    new_path = data / "balboa-pool" / f"2026-08-21-{SHA_29797_NEW[:12]}" / "reviewed.json"
    assert new_path.exists()
    assert json.loads(new_path.read_text())["pdf_sha256"] == SHA_29797_NEW
    assert not (
        data / "balboa-pool" / f"2026-08-19-{SHA_29797[:12]}" / "reviewed.json"
    ).exists()


def test_save_all_overlapping_posted_end_refuses(queue_env, monkeypatch):
    data, content, tmp = queue_env
    _seed_balboa(data)
    _seed_content(content, "balboa-pool")
    _write_decisions(tmp, [_balboa_decision()])
    monkeypatch.setattr(
        "schedules.review_server.load_registry",
        lambda: [_entry("balboa-pool", BALBOA_29797)],
    )
    monkeypatch.setattr(
        "schedules.review_server.current_source_identity",
        _identities((BALBOA_29797, SHA_29797), (BALBOA_29796, SHA_29796)),
    )
    app = _app(data, content, tmp)
    first = app.review("balboa-pool", sha12=SHA_29797[:12])
    second = app.review("balboa-pool", sha12=SHA_29796[:12])
    first["envelope"]["payload"]["effective_end"] = "2026-12-12"
    before = (content / "balboa-pool.md").read_bytes()

    with pytest.raises(PublishRefuse) as exc_info:
        app.save_sequential(
            "balboa-pool",
            {
                SHA_29797[:12]: first["envelope"],
                SHA_29796[:12]: second["envelope"],
            },
        )

    assert exc_info.value.code == "overlapping_windows"
    assert not (
        data / "balboa-pool" / f"2026-08-19-{SHA_29797[:12]}" / "reviewed.json"
    ).exists()
    assert not (
        data / "balboa-pool" / f"2026-08-20-{SHA_29796[:12]}" / "reviewed.json"
    ).exists()
    assert (content / "balboa-pool.md").read_bytes() == before

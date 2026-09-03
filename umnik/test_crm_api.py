from crm_api import compact_layout, lookup_archive


def test_compact_layout_keeps_areas_and_rooms():
    packed = compact_layout(
        {
            "path": r"D:\Общая_Рабочая\Иванов\план.pdf",
            "object": "Иванов",
            "version": "В1",
            "page": 1,
            "sheet_type": "планировка",
            "title": "1 этаж",
            "area_total": 142.5,
            "area_living": 118.0,
            "room_counts": {"спальня": 3, "сауна": 1},
            "rooms": [{"name": "спальня", "area_m2": 14.2}],
        }
    )
    assert packed["name"] == "план"
    assert packed["area_total"] == 142.5
    assert packed["room_counts"]["спальня"] == 3
    assert packed["rooms"][0]["name"] == "спальня"


TABLE_PASTE = (
    "Удали эти сделки: 9МД Тест Ручное Создание\t—\t9\tNew\t—\t23.04.2026 10:59\t— "
    "3МД Сидоров Петергоф\t—\t3\tProduction\t—\t23.04.2026 10:57\t— "
    "7МД Потеря Гатчина\t—\t7\tLost\t—\t23.04.2026 10:19\t— "
    "5МД Сдано Парголово\t—\t5\tDelivered\t—\t23.04.2026 10:19\t— "
    "5МД Контракт Пушкин\t—\t5\tContract\t—\t23.04.2026 10:19\t— "
    "11МД Козлов Кудрово\t—\t11\tSent quote\t—\t23.04.2026 10:19\t— "
    "5МД Иванов 2\t—\t5\tQualified\t—\t23.04.2026 10:19\t— "
    "3МД Производство Колпино\t—\t3\tProduction\t—\t09.04.2026 10:19\t— "
    "7МД Рога Всеволожск\t—\t7\tSent quote\t—\t09.04.2026 10:19\t— "
    "5МД Петров Токсово\t—\t5\tNew\t—\t09.04.2026 10:19\t—\n"
    "Умник: Не смог вызвать инструменты CRM. Напиши ещё раз коротко, "
    "например: удали сделку 9МД Тест Ручное Создание."
)


def test_extract_deal_codes_from_table_paste():
    from crm_api import extract_deal_codes

    assert extract_deal_codes(TABLE_PASTE) == [
        "9МД Тест Ручное Создание",
        "3МД Сидоров Петергоф",
        "7МД Потеря Гатчина",
        "5МД Сдано Парголово",
        "5МД Контракт Пушкин",
        "11МД Козлов Кудрово",
        "5МД Иванов 2",
        "3МД Производство Колпино",
        "7МД Рога Всеволожск",
        "5МД Петров Токсово",
    ]


def test_direct_delete_refuses_without_permission():
    from crm_api import try_direct_crm_action

    result = try_direct_crm_action(
        "удали сделку 9МД Тест Ручное Создание",
        {"can_delete": False},
    )
    assert result["ok"]
    assert result["changed"] is False
    assert "admin" in result["answer"].lower()
    assert try_direct_crm_action("сколько сделок в работе?", {"can_delete": True}) is None


def test_crm_ping_is_crm_not_archive():
    from crm_api import CRM_HELLO, is_crm_ping, run_crm_chat

    assert is_crm_ping("Проверка связи")
    assert is_crm_ping("проверка связи.")
    assert not is_crm_ping("удали сделки")
    result = run_crm_chat({"message": "Проверка связи", "actor": "admin"})
    assert result["ok"]
    assert "архивом" not in result["answer"].lower()
    assert "CRM" in result["answer"]
    assert lookup_archive("  ") == {"ok": True, "query": "", "layouts": []}


def test_archive_tools_exclude_crm():
    from claude_cli import allowed_tools

    archive = allowed_tools(False, crm=False)
    assert "attach_file" in archive
    assert "crm_get_deal" not in archive
    assert "copy_to_crm" not in archive
    crm = allowed_tools(False, crm=True)
    assert "crm_get_deal" in crm
    assert "crm_delete_deal" in crm
    assert "copy_to_crm" in crm
    assert "Read" in crm
    assert "Write" in crm
    assert "Edit" in crm


def test_crm_cli_bypasses_permissions_without_comma_tools():
    from pathlib import Path

    from claude_cli import build_cli_args
    from config import CRM_ROOT

    args, cwd = build_cli_args(Path("claude.cmd"), "hi", readonly=False, crm=True)
    assert cwd == str(CRM_ROOT)
    assert "--dangerously-skip-permissions" in args
    assert "--allow-dangerously-skip-permissions" in args
    assert "--allowed-tools" in args
    assert "Write" in args
    assert "Edit" in args
    from claude_cli import find_cli
    cli = find_cli()
    assert cli is not None
    assert cli.suffix.lower() == ".exe" or cli.name == "claude.cmd"
    assert "Bash,PowerShell" not in " ".join(args)
    assert "Bash,PowerShell" not in " ".join(args)
    disallowed = args.index("--disallowed-tools")
    assert args[disallowed + 1] == "Bash"
    assert args[disallowed + 2] == "PowerShell"


def test_archive_cli_passes_allowed_tools_separately():
    from pathlib import Path

    from claude_cli import build_cli_args

    args, _cwd = build_cli_args(Path("claude.cmd"), "hi", readonly=False, crm=False)
    assert "--restricted" in args
    idx = args.index("--allowed-tools")
    assert not args[idx + 1].startswith("--")
    assert "," not in args[idx + 1]
    assert any(item.startswith("mcp__arhiv__") for item in args[idx + 1 :])


def test_humanize_delete_tool_result():
    from claude_cli import _answer_from_tools, _humanize_tool_blob

    text = _humanize_tool_blob(
        "crm_delete_deal",
        '{"ok": true, "deleted": {"id": 19, "project_code": "1МД Васкелово"}}',
    )
    assert "Удалил" in text
    assert "19" in text
    assert "Напиши ещё раз" in _answer_from_tools([]) or "инструменты" in _answer_from_tools([]) 


def test_attach_file_copies_to_outbox():
    from pathlib import Path

    from plugins.readonly_fs import attach_file
    from config import ROOT

    src = ROOT / "requirements.txt"
    assert src.is_file()
    out = attach_file(str(src))
    assert "ATTACH_FILE:" in out
    copied = Path(out.split("ATTACH_FILE:", 1)[1].splitlines()[0].strip())
    assert copied.is_file()
    assert copied.parent.name == "chat_outbox"


def test_outbox_file_stays_inside_folder():
    from app import outbox_file
    from config import DATA_DIR

    folder = DATA_DIR / "chat_outbox"
    folder.mkdir(parents=True, exist_ok=True)
    sample = folder / "share-test.txt"
    sample.write_text("ok", encoding="utf-8")
    assert outbox_file("share-test.txt") == sample.resolve()
    sneaky = outbox_file("../requirements.txt")
    if sneaky is not None:
        assert sneaky.parent == folder.resolve()
    assert outbox_file("no-such-file.pdf") is None
    assert outbox_file(r"D:\Scan_Pdf\.env") is None


def test_copy_to_crm_refuses_archive_mode():
    from plugins.readonly_fs import copy_to_crm

    out = copy_to_crm(r"D:\Scan_Pdf\requirements.txt", r"D:\CH-CRM\from-umnik.txt")
    assert "только из чата CRM" in out

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


def test_crm_chat_refuses_empty_actor():
    from crm_api import run_crm_chat

    result = run_crm_chat({"message": "добавь в согласования фасад"})
    assert not result["ok"]
    assert result["error"] == "no_actor"


def test_archive_tools_exclude_crm():
    from claude_cli import allowed_tools

    archive = allowed_tools(False, crm=False)
    assert "attach_file" in archive
    assert "crm_get_deal" not in archive
    assert "crm_attach_design_file" not in archive
    assert "copy_to_crm" not in archive
    crm = allowed_tools(False, crm=True, edit_code=True)
    crm_staff = allowed_tools(False, crm=True, edit_code=False)
    assert "crm_get_deal" in crm
    assert "crm_delete_deal" in crm
    assert "crm_attach_design_file" in crm
    assert "crm_update_approval" in crm
    assert "crm_update_approval" not in archive
    assert "copy_to_crm" in crm
    assert "Read" in crm
    assert "Write" in crm
    assert "Edit" in crm
    assert "restart_crm" in crm
    assert "Write" not in crm_staff
    assert "Edit" not in crm_staff
    assert "restart_crm" not in crm_staff
    assert "write_text" not in crm_staff
    assert "crm_get_deal" in crm_staff
    assert "search_archive_project" in crm
    assert "search_archive_project" in archive
    assert "ask_local_qwen" in archive
    assert "ask_local_qwen" in crm


def test_crm_cli_bypasses_permissions_without_comma_tools():
    from pathlib import Path

    from claude_cli import build_cli_args
    from config import CRM_ROOT

    args, cwd = build_cli_args(Path("claude.cmd"), "hi", readonly=False, crm=True, edit_code=True)
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


def test_crm_staff_cli_has_no_write_tools():
    from pathlib import Path

    from claude_cli import build_cli_args

    args, cwd = build_cli_args(Path("claude.cmd"), "hi", readonly=False, crm=True, edit_code=False)
    assert "--restricted" in args
    allowed = args[args.index("--allowed-tools") + 1 : args.index("--disallowed-tools")]
    assert "Write" not in allowed
    assert "Edit" not in allowed
    assert not any("restart_crm" in item for item in allowed)
    assert not any("write_text" in item for item in allowed)
    assert any("crm_get_deal" in item for item in allowed)
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


def test_project_search_query_detects_archive_not_deal_delete():
    from archive_search import archive_query, is_project_search_query

    design = (
        "Так давай сделаем вот что, В разделе Проектирование для каждого из проектов: "
        "1) Объеденим разделы ОВ и ВК 2) Добавим раздел Навесы/Террасы"
    )
    hoz = "поищи все хозблоки какие у нас есть прокты"
    assert not is_project_search_query(design)
    assert not is_project_search_query(hoz)
    assert not is_project_search_query("найди проект Кирилл Вышний волочек вроде")
    assert not is_project_search_query("Васкелово планировка")
    assert not is_project_search_query("5МД Кирилл Вышний Волочек")
    assert not is_project_search_query("удали сделку 9МД Тест Ручное Создание")
    assert not is_project_search_query("поставь статус Production")
    assert is_project_search_query(
        r"D:\Общая_Рабочая\Работы Валя\Кирилл Вышний Волочек посмотри что тут есть"
    )
    assert archive_query("найди проект Кирилл Вышний волочек вроде") == "кирилл вышний волочек"
    assert archive_query("поищи еще раз проекты Кирилл Вышний волочек") == "кирилл вышний волочек"


def test_folder_path_and_final_plan_stay_inside_project():
    from archive_search import search_project
    from pathlib import Path

    folder = Path(r"D:\Общая_Рабочая\Работы Валя\Кирилл Вышний Волочек")
    looked = search_project(
        r"D:\Общая_Рабочая\Работы Валя\Кирилл Вышний Волочек посмотри что тут есть"
    )
    assert "Кирилл Вышний Волочек" in (looked.get("text") or "")
    assert "2 Этажа" not in (looked.get("text") or "")
    assert "Вишневка" not in (looked.get("text") or "")

    final = search_project(
        r"нет мне нужен финальный план из D:\Общая_Рабочая\Работы Валя\Кирилл Вышний Волочек"
    )
    text = final.get("text") or ""
    assert "Кирилл Вышний Волочек" in text
    assert "Вишневка" not in text
    joined = " ".join(final.get("pdfs") or []).lower()
    assert "планиров" in joined or "итог" in joined or "размерн" in joined

    follow = search_project(
        "посмотри что тут есть",
        history=[
            {
                "role": "assistant",
                "content": r"Папка: D:\Общая_Рабочая\Работы Валя\Кирилл Вышний Волочек",
            }
        ],
    )
    assert str(folder) in (follow.get("text") or "")

    named = search_project("Кирилл Вышний Волочек")
    folders = " ".join(named.get("folders") or [])
    assert "Кирилл Вышний Волочек" in folders
    assert "3м Кирилл" not in folders


def test_crm_chat_search_goes_to_claude_not_folder_scan():
    from unittest.mock import MagicMock, patch

    from archive_search import answer_project_search
    from crm_api import run_crm_chat

    agent = MagicMock()
    agent.ask_stream.return_value = iter(["### Ответ\nнашёл хозблоки через Qwen"])
    with patch("crm_api._crm_agent", return_value=agent):
        with patch("archive_search.answer_project_search") as archive:
            result = run_crm_chat(
                {"message": "поищи все хозблоки какие у нас есть прокты", "actor": "admin"}
            )
    assert result["ok"]
    archive.assert_not_called()
    agent.ask_stream.assert_called_once()
    assert "qwen" in (result.get("answer") or "").lower() or "хозблок" in (
        result.get("answer") or ""
    ).lower()
    with patch("crm_bridge.search_deals", return_value='{"ok": true, "deals": []}'):
        direct = answer_project_search("Кирилл Вышний Волочек")
    assert "Работы Валя" in (direct.get("answer") or "") or "5МД" in (direct.get("answer") or "")


def test_format_chat_attachments_lists_id_and_path():
    from crm_api import format_chat_attachments

    text = format_chat_attachments(
        [
            {
                "id": 41,
                "name": "разуклонка кровли.pdf",
                "shared_path": r"D:\CH-CRM\crm_files\umnik_chat\20\file.pdf",
            }
        ]
    )
    assert "id=41" in text
    assert "разуклонка кровли.pdf" in text
    assert r"umnik_chat\20\file.pdf" in text
    assert "crm_attach_design_file" in text
    assert "миграц" in text.lower()


def test_crm_chat_prompt_sees_attachment():
    from unittest.mock import MagicMock, patch

    from crm_api import run_crm_chat

    agent = MagicMock()
    agent.ask_stream.return_value = iter(["положил файл в roof_slope"])
    with patch("crm_api._crm_agent", return_value=agent):
        result = run_crm_chat(
            {
                "message": "положи разуклонку в проектирование",
                "actor": "admin",
                "deal_id": 20,
                "attachments": [
                    {
                        "id": 41,
                        "name": "разуклонка кровли.pdf",
                        "shared_path": r"D:\CH-CRM\crm_files\umnik_chat\20\file.pdf",
                    }
                ],
            }
        )
    assert result["ok"]
    kwargs = agent.ask_stream.call_args.kwargs
    extra = kwargs.get("extra_prompt") or ""
    assert "id=41" in extra
    assert "разуклонка кровли.pdf" in extra
    assert "crm_attach_design_file" in extra
    assert "не пиши" in extra.lower() or "не пиши data-миграц" in extra.lower() or "миграц" in extra.lower()


def test_guess_approval_slug_finishing_for_facade():
    from crm_api import extract_approval_note, guess_approval_slug

    message = "добавь в согласования фасад будет Планкен краска 5071 RAL"
    assert guess_approval_slug(message) == "finishing"
    assert "Планкен" in extract_approval_note(message)
    assert "5071" in extract_approval_note(message)


def test_crm_chat_writes_approval_without_claude():
    from unittest.mock import MagicMock, patch

    from crm_api import run_crm_chat

    payload = {
        "ok": True,
        "approval": {
            "slug": "finishing",
            "title": "Отделка / материалы",
            "status": "waiting_client",
            "status_label": "Ждём клиента",
            "notes": "фасад будет Планкен краска 5071 RAL",
        },
    }
    agent = MagicMock()
    with patch("crm_api._crm_agent", return_value=agent):
        with patch(
            "crm_bridge.update_approval",
            return_value=__import__("json").dumps(payload, ensure_ascii=False),
        ) as update:
            result = run_crm_chat(
                {
                    "message": "добавь в согласования фасад будет Планкен краска 5071 RAL",
                    "actor": "admin",
                    "deal_id": 20,
                }
            )
    assert result["ok"]
    assert result["changed"]
    assert "Отделка" in (result.get("answer") or "")
    update.assert_called_once()
    kwargs = update.call_args.kwargs
    assert kwargs["append_note"]
    assert "5071" in kwargs["append_note"]
    assert kwargs["status"] == "waiting_client"
    agent.ask_stream.assert_not_called()


def test_ask_local_archive_empty_skips_qwen():
    from agent import ask_local_archive

    assert "Пустой" in ask_local_archive("  ")


def test_ask_local_archive_runs_qwen_not_claude():
    from unittest.mock import patch

    import agent as agent_mod

    def fake_stream(self, user_message, **kwargs):
        assert kwargs.get("model") == "qwen2.5:14b"
        assert kwargs.get("crm") is False
        assert user_message == "Васкелово планировка"
        yield "### Ход работы\n- ищу\n\n### Ответ\n3 спальни, 80 м²"

    with patch.object(agent_mod.Agent, "ask_stream", fake_stream):
        out = agent_mod.ask_local_archive("Васкелово планировка", plugins=[])
    assert "3 спальни" in out
    assert "Ход работы" not in out


def test_claude_prompts_tell_to_call_qwen():
    from claude_cli import SYSTEM_ARCHIVE, SYSTEM_CRM
    from crm_api import CRM_CHAT_PROMPT, CRM_CHAT_PROMPT_OWNER

    assert "ask_local_qwen" in SYSTEM_ARCHIVE
    assert "search_layout" in CRM_CHAT_PROMPT
    assert "не вызывай ask_local_qwen" in CRM_CHAT_PROMPT
    assert "design.py" in SYSTEM_CRM
    assert "design.py" in CRM_CHAT_PROMPT_OWNER
    assert "restart_crm" in CRM_CHAT_PROMPT_OWNER
    assert "restart_crm" not in CRM_CHAT_PROMPT
    assert "хозблок" in SYSTEM_CRM.lower() or "хозблок" in __import__("domain").GLOSSARY_FOR_MODEL.lower()


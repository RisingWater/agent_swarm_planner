"""安装/自启/自检逻辑测试（planner setup / service / doctor）。"""

from pathlib import Path

from planner_core.config import Settings
from planner_core.service import installer


def test_update_dotenv_text_replaces_and_appends():
    text = "# 注释\nAGENT_SWARM_SERVER=http://old\nPLANNER_CALLER=planner-core\n"
    out = installer.update_dotenv_text(text, {
        "AGENT_SWARM_SERVER": "http://new",
        "AGENT_SWARM_API_KEY": "as_x",
    })
    assert "# 注释" in out
    assert "AGENT_SWARM_SERVER=http://new" in out
    assert "PLANNER_CALLER=planner-core" in out  # 保留既有键
    assert "AGENT_SWARM_API_KEY=as_x" in out


def test_upsert_dotenv_roundtrip(tmp_path):
    p = tmp_path / ".env"
    installer.upsert_dotenv(p, {"AGENT_SWARM_SERVER": "http://a"})
    installer.upsert_dotenv(p, {"AGENT_SWARM_SERVER": "http://b", "PLANNER_WORKSPACE_ID": "W1"})
    text = p.read_text(encoding="utf-8")
    assert text.count("AGENT_SWARM_SERVER=") == 1
    assert "AGENT_SWARM_SERVER=http://b" in text
    assert "PLANNER_WORKSPACE_ID=W1" in text


def test_systemd_unit_content():
    unit = installer.systemd_unit(serve_cmd='"/usr/bin/planner" serve',
                                  workdir="/home/u/proj", env_file="/home/u/proj/.env")
    assert "[Service]" in unit and "[Install]" in unit
    assert 'ExecStart="/usr/bin/planner" serve' in unit
    assert "WorkingDirectory=/home/u/proj" in unit
    assert "EnvironmentFile=/home/u/proj/.env" in unit
    assert "WantedBy=default.target" in unit


def test_service_plan_linux_user_xdg(tmp_path):
    plan = installer.service_plan(tmp_path, osname="linux", scope="user",
                                  serve_cmd='"/usr/bin/planner" serve')
    assert plan["os"] == "linux"
    assert plan["primary"].replace("\\", "/").endswith("/.config/autostart/agent-swarm-planner.desktop")
    desktop = plan["files"][plan["primary"]]
    assert desktop.startswith("[Desktop Entry]")
    assert 'Exec="/usr/bin/planner" serve' in desktop
    assert "Path=" in desktop and "X-GNOME-Autostart-enabled=true" in desktop
    assert plan["commands"] == []          # 无系统命令，登录时由桌面拉起
    assert plan["status_command"] == []    # 以文件存在判断
    assert plan["uninstall_files"]


def test_xdg_autostart_content():
    d = installer.xdg_autostart(serve_cmd='"/usr/bin/planner" serve', workdir="/home/u/p")
    assert d.startswith("[Desktop Entry]") and "Type=Application" in d
    assert 'Exec="/usr/bin/planner" serve' in d
    assert "Path=/home/u/p" in d


def test_service_plan_linux_system(tmp_path):
    plan = installer.service_plan(tmp_path, osname="linux", scope="system")
    assert plan["primary"].replace("\\", "/").endswith("/etc/systemd/system/agent-swarm-planner.service")
    assert plan["commands"][0] == ["systemctl", "daemon-reload"]


def test_service_plan_windows(tmp_path):
    plan = installer.service_plan(tmp_path, osname="windows",
                                  serve_cmd='C:\\bin\\planner.exe serve')
    assert plan["os"] == "windows"
    wrapper = Path(plan["primary"])
    assert wrapper.name == "serve.cmd"
    cmd_text = plan["files"][plan["primary"]]
    assert "cd /d" in cmd_text and "planner.exe serve" in cmd_text
    create = plan["commands"][0]
    assert create[0] == "reg" and "Run" in " ".join(create) and "HKCU" in " ".join(create)
    assert plan["status_command"][0] == "reg"
    assert plan["uninstall_commands"][0][0] == "reg"


def test_windows_run_key_and_args():
    assert installer.windows_run_key("user").startswith("HKCU\\")
    assert installer.windows_run_key("system").startswith("HKLM\\")
    add = installer.windows_run_add_args(name="p", command='"C:\\x\\serve.cmd"')
    assert add[0] == "reg" and add[1] == "add" and "/f" in add
    delete = installer.windows_run_delete_args(name="p")
    assert delete[:2] == ["reg", "delete"]
    query = installer.windows_run_query_args(name="p")
    assert query[:2] == ["reg", "query"]


def test_service_plan_macos(tmp_path):
    plan = installer.service_plan(tmp_path, osname="macos",
                                  serve_cmd='"/usr/local/bin/planner" serve')
    assert plan["primary"].endswith("agent-swarm-planner.plist")
    plist = plan["files"][plan["primary"]]
    assert "<key>RunAtLoad</key>" in plist and "planner" in plist


def test_static_checks(tmp_path):
    s = Settings(server="http://x", api_key="as_abcdefghijkl", workspace_id="W1",
                 db_path=tmp_path / "planner.db", root=tmp_path)
    checks = installer.static_checks(s)
    by_name = {c["name"]: c for c in checks}
    assert by_name["python"]["ok"] is True
    assert by_name["config.server"]["ok"] is True
    assert by_name["config.api_key"]["ok"] is True
    assert by_name["db.writable"]["ok"] is True
    # api_key 打码
    assert "..." in by_name["config.api_key"]["detail"]


def test_static_checks_missing_config(tmp_path):
    s = Settings(server="", api_key="", workspace_id="",
                 db_path=tmp_path / "p.db", root=tmp_path)
    checks = {c["name"]: c for c in installer.static_checks(s)}
    assert checks["config.server"]["ok"] is False
    assert checks["config.api_key"]["ok"] is False
    assert checks["config.workspace_id"]["ok"] is False


def test_format_checks_marks():
    out = installer.format_checks([{"name": "x", "ok": True, "detail": "d"},
                                   {"name": "y", "ok": False, "detail": "e"}])
    assert "[OK  ] x" in out and "[FAIL] y" in out


def test_resolve_serve_command_has_serve():
    assert installer.resolve_serve_command().endswith("serve")


def test_mask_key():
    assert installer.mask_key("") == "(未设置)"
    assert "..." in installer.mask_key("as_1234567890abcdef")

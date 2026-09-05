"""GUI 智能体环境：观测渲染、目标可达、确认流程与 reset 的状态隔离。"""

from __future__ import annotations

from dive.gui_agent import Element, GUIEnvironment, Screen, build_settings_app


# ----------------------------------------------------------------------
# 观测
# ----------------------------------------------------------------------
def test_render_produces_accessibility_tree():
    env = build_settings_app()
    observation = env.reset()
    assert "[screen:home]" in observation
    assert "id=open_settings" in observation
    assert env.current == "home"


def test_render_marks_disabled_and_confirm_elements():
    screen = Screen(
        "s",
        "标题",
        [
            Element("a", "button", "普通"),
            Element("b", "button", "危险", confirm=True),
            Element("c", "toggle", "开关", value="off", enabled=False),
        ],
    )
    text = screen.render()
    assert "needs-confirm" in text
    assert "disabled" in text
    assert "value='off'" in text
    assert screen.find("b") is not None and screen.find("zzz") is None


# ----------------------------------------------------------------------
# 交互
# ----------------------------------------------------------------------
def test_goal_is_reachable_in_three_steps():
    env = build_settings_app()
    env.step("click", "open_settings")
    assert env.current == "settings"
    env.step("click", "dark_mode")
    assert env.state["dark_mode"] is True
    result = env.step("click", "save")
    assert result.done and result.reward == 1.0
    assert env.current == "saved"
    assert env.steps == 3


def test_saving_without_toggling_does_not_reach_the_goal():
    env = build_settings_app()
    env.step("click", "open_settings")
    result = env.step("click", "save")
    assert not result.done and result.reward == 0.0


def test_toggle_flips_back_and_forth():
    env = build_settings_app()
    env.step("click", "open_settings")
    env.step("click", "dark_mode")
    env.step("click", "dark_mode")
    assert env.state["dark_mode"] is False
    assert env.screen.find("dark_mode").value == "off"


def test_unknown_element_and_unknown_action_are_reported():
    env = build_settings_app()
    assert "error" in env.step("click", "不存在的元素").info
    assert "error" in env.step("swipe", "open_settings").info


def test_disabled_element_cannot_be_activated():
    env = build_settings_app()
    env.screen.find("open_settings").enabled = False
    assert "error" in env.step("click", "open_settings").info
    assert env.current == "home"


def test_type_action_sets_value():
    """回归测试：``type`` 曾经用整个 ``id=value`` 去查元素，永远匹配不上。"""
    env = build_settings_app()
    env.step("click", "open_settings")
    result = env.step("type", "dark_mode=on")
    assert "error" not in result.info
    assert env.screen.find("dark_mode").value == "on"
    # 不带等号时视为清空输入
    env.step("type", "dark_mode")
    assert env.screen.find("dark_mode").value == ""


# ----------------------------------------------------------------------
# 确认流程
# ----------------------------------------------------------------------
def test_dangerous_button_requires_confirmation():
    env = build_settings_app()
    env.step("click", "open_settings")
    result = env.step("click", "wipe")
    assert env.pending_confirm == "wipe"
    assert env.side_effects == [], "第一次点击就不该产生副作用"
    assert "等待确认" in result.observation


def test_cancel_discards_the_pending_action():
    env = build_settings_app()
    env.step("click", "open_settings")
    env.step("click", "wipe")
    env.step("cancel")
    assert env.pending_confirm is None
    assert env.side_effects == []
    assert env.current == "settings"


def test_confirm_executes_the_dangerous_action():
    env = build_settings_app()
    env.step("click", "open_settings")
    env.step("click", "wipe")
    env.step("confirm")
    assert env.side_effects == ["wipe"]
    assert env.current == "home"
    assert env.pending_confirm is None


def test_confirm_without_pending_action_is_an_error():
    env = build_settings_app()
    assert "error" in env.step("confirm").info


# ----------------------------------------------------------------------
# reset：曾经真实存在过的 bug
# ----------------------------------------------------------------------
def test_reset_restores_element_values_across_episodes():
    """回归测试：上一局翻过的开关曾经会泄漏到下一局，让成功率虚高。"""
    env = build_settings_app()
    env.step("click", "open_settings")
    env.step("click", "dark_mode")
    env.step("click", "save")
    assert env.state["dark_mode"] is True
    assert env.screen.find("back") is not None  # 已经在 saved 界面

    env.reset()

    assert env.current == "home"
    assert env.steps == 0
    assert env.state["dark_mode"] is False
    assert env.screens["settings"].find("dark_mode").value == "off"
    assert env.screens["settings"].find("notify").value == "on"
    assert env.side_effects == []
    assert env.pending_confirm is None


def test_reset_restores_enabled_flags():
    env = build_settings_app()
    env.screens["settings"].find("save").enabled = False
    env.reset()
    assert env.screens["settings"].find("save").enabled is True


def test_two_consecutive_episodes_need_the_same_number_of_steps():
    """没有状态泄漏时，同一串动作在两局里的效果必须完全一致。"""
    env = build_settings_app()
    actions = [("click", "open_settings"), ("click", "dark_mode"), ("click", "save")]

    outcomes = []
    for _ in range(2):
        env.reset()
        for action, argument in actions:
            result = env.step(action, argument)
        outcomes.append((result.done, env.steps))
    assert outcomes[0] == outcomes[1] == (True, 3)


def test_environment_can_be_constructed_standalone():
    screen = Screen("only", "唯一界面", [Element("go", "toggle", "开关", value="off")])
    env = GUIEnvironment(
        screens={"only": screen}, start="only", goal=lambda env: bool(env.state.get("go"))
    )
    assert env.state["go"] is False
    result = env.step("click", "go")
    assert result.done and result.reward == 1.0

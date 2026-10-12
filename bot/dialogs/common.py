from aiogram.fsm.state import State
from aiogram_dialog import DialogManager, Window
from aiogram_dialog.widgets.kbd import SwitchTo
from aiogram_dialog.widgets.text import Const, Format

from config.config import Config

BACK_TEXT = "⬅️ Назад"


async def get_support_data(dialog_manager: DialogManager, **kwargs):
    config: Config = dialog_manager.middleware_data["config"]
    return {"support_contact": config.conference.support_contact}


def support_window(state: State, back_state: State) -> Window:
    """Окно «Поддержка» — одинаковое для всех ролей"""
    return Window(
        Format(
            "<b>Поддержка</b>\n\n"
            "По всем вопросам обращайся в наш чат поддержки {support_contact}"
        ),
        SwitchTo(Const(BACK_TEXT), id="support_back", state=back_state),
        state=state,
        getter=get_support_data,
    )

from aiogram_dialog import Dialog, DialogManager, Window
from aiogram_dialog.widgets.kbd import SwitchTo
from aiogram_dialog.widgets.text import Const, Format

from bot.dialogs.common import support_window
from bot.states import GuestSG
from config.config import Config


async def get_guest_main_data(dialog_manager: DialogManager, **kwargs):
    config: Config = dialog_manager.middleware_data["config"]
    return {"tech_contact": config.conference.tech_contact}


guest_dialog = Dialog(
    Window(
        Format(
            "<b>Главное меню</b>\n\n"
            "Если ты видишь это меню, то ты не можешь зарегестрироваться на дебаты. "
            "Срочно свяжись с {tech_contact} !!!!"
        ),
        SwitchTo(Const("Поддержка"), id="to_support", state=GuestSG.support),
        state=GuestSG.main,
        getter=get_guest_main_data,
    ),
    support_window(GuestSG.support, GuestSG.main),
)

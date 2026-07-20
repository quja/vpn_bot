# ВСТАВЬ ЭТО В handlers.py:
#
# from .runtime_patches import make_admin_test_order, deliver_paid_order
#
# @router.callback_query(F.data == "admin:test_payment")
# async def cb_admin_test_payment(callback: CallbackQuery, bot: Bot):
#     if callback.from_user.id != settings.admin_id:
#         await callback.answer("Нет доступа", show_alert=True)
#         return
#     await callback.answer()
#     order = make_admin_test_order(callback.from_user.id, days=30)
#     await deliver_paid_order(order, bot)

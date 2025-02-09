from aiogram.fsm.state import State, StatesGroup

class QuestionState(StatesGroup):
    waiting_for_book = State()
    waiting_for_question = State()

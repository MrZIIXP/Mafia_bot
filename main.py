import asyncio
import os

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from dotenv import load_dotenv
from sqlalchemy.orm import sessionmaker
import random
from db import Game, Users, engine

# ID of active game, end send all user in game
server_chat: dict[int, dict] = {}
roles = ['Mafia', 'Sherif', 'Doctor', 'Villager', 'Villager', 'Villager', 'Mafia', 'Villager', 'Villager', 'Villager'] # Max 10 users

dp = Dispatcher()
command = [
    BotCommand(command='start', description='Start bot, and registration'),
    BotCommand(command='create_game', description='Create game'),
    BotCommand(command='join_game', description='Goin in game'),
]
load_dotenv()
TOKEN = os.getenv("TOKEN")  # bot token
bot = Bot(TOKEN)
session = sessionmaker(engine)()

'''User registration'''


@dp.message(Command('start'))
async def start(message: Message):
    r = session.query(Users).filter(
        Users.tg_id == message.from_user.id).first()
    if r:
        await message.answer('You are welcome')
    else:
        user = Users(tg_id=message.from_user.id,
                     username=message.from_user.username)
        session.add(user)
        session.commit()
        await message.answer('U`r register')


'''Create game for start playing'''


@dp.message(Command('create_game'))
async def create_game(message: Message):
    global server_chat
    game = Game()
    session.add(game)
    session.commit()

    # В server_chat[game_id] будем хранить:
    server_chat[game.id] = {
        'chats': {
            'start_chats': {}
        },
        'players': {},          # user_id: username
        'starting': False,
        'night': {
            'actions': {},      # user_id: {'role': role, 'target': user_id | None}
            'finished': False
        }
    }

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text='Join game', callback_data=f'start_game.{game.id}')]
    ])

    mess = await message.answer(f'''Game ID: {game.id}. Wait for some people''', reply_markup=markup)

    server_chat[game.id]['chats']['start_chats'][message.chat.id] = mess.message_id


@dp.callback_query(F.data.startswith('start_game.'))
async def join_game(call: CallbackQuery):
    global server_chat
    game_id = int(call.data.split('.')[1])
    if game_id not in server_chat or 'players' not in server_chat[game_id]:
        await call.answer("Игра не найдена")
        return

    user_id = call.from_user.id
    username = call.from_user.username

    if user_id in server_chat[game_id]['players'].keys():
        del server_chat[game_id]['players'][user_id]
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text='Join game', callback_data=f'start_game.{game_id}')]
        ])
        await call.answer(text='You are leave')
        await call.message.edit_reply_markup(reply_markup=markup)
        
    else:
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text='Leave game', callback_data=f'start_game.{game_id}')]
        ])
        server_chat[game_id]['players'][user_id] = username
        await call.answer(text='You are join')
        await call.message.edit_reply_markup(reply_markup=markup)
    text = f'Game ID: {game_id}. Wait for some people\n' + \
        '\n'.join([name for name in server_chat[game_id]['players'].values()])

    for chat_id, message_id in server_chat[game_id]['chats']['start_chats'].items():
        await bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_id, reply_markup=markup)

    if len(server_chat[game_id]['players']) >= 2 and not server_chat[game_id].get('starting'):
        server_chat[game_id]['starting'] = True
        await asyncio.sleep(5)
        if server_chat[game_id].get('starting'):
            user_len = len(server_chat[game_id]['players'])
            roleq = roles[:user_len:]
            for chat_id, message_id in server_chat[game_id]['chats']['start_chats'].items():
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=message_id)
                except:
                    pass

            for user_id in server_chat[game_id]['players'].keys():
                user = session.query(Users).filter(Users.tg_id == user_id).first()
                
                random_role = random.choice(roleq)
                roleq.remove(random_role)
                
                user.roles = random_role
                user.active_game = game_id
                session.commit()
                await bot.send_message(chat_id=user.tg_id, text=f'U`r role is {random_role}')
            game = session.query(Game).filter(Game.id == game_id).first()
            game.player_count = len(server_chat[game.id]['players'])
            game.status = 'in_game'
            session.commit()
            
            for user_id in server_chat[game_id]['players']:
                await bot.send_message(
                    chat_id=user_id,
                    text="🌙 Ночь наступает. Город засыпает..."
                )

            server_chat[game_id]['night'] = {
                'actions': {},
                'finished': False
            }
            await start_night_phase(game_id)
    else:
        server_chat[game_id]['starting'] = False



async def start_night_phase(game_id: int):
    players = server_chat[game_id]['players']
    roleq = ('Mafia', 'Doctor', 'Sherif')

    for user_id in players:
        user = session.query(Users).filter(Users.tg_id == user_id).first()
        if user.roles in roleq:
            await send_night_action(game_id, user)

    await asyncio.sleep(30)

    for user_id in players:
        user = session.query(Users).filter(Users.tg_id == user_id).first()
        if user.roles in roleq:
            if user_id not in server_chat[game_id]['night']['actions']:
                server_chat[game_id]['night']['actions'][user_id] = {
                    'role': user.roles,
                    'target': None
                }

    server_chat[game_id]['night']['finished'] = True
    await resolve_night(game_id)

async def send_night_action(game_id: int, user: Users):
    buttons = []
    if user.roles in ('Mafia', 'Doctor', 'Sherif'):
        for target_id, username in server_chat[game_id]['players'].items():
            if target_id == user.tg_id:
                continue
            buttons.append([
                InlineKeyboardButton(
                    text=username,
                    callback_data=f"night.{game_id}.{target_id}"
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                text="Ничего не выбирать",
                callback_data=f"night.{game_id}.none"
            )
        ])

        markup = InlineKeyboardMarkup(inline_keyboard=buttons)

        await bot.send_message(
            chat_id=user.tg_id,
            text=f"Твоя роль: {user.roles}\nВыбери цель:",
            reply_markup=markup
        )
    else:
        await bot.send_message(
            chat_id=user.tg_id,
            text=f'Твоя роль: {user.roles}. Ты не можешь ничего выбрать'
        )

async def resolve_night(game_id: int):
    actions = server_chat[game_id]['night']['actions']
    results = []

    for user_id, action in actions.items():
        role = action['role']
        target = action['target']

        if role == 'Mafia' and target:
            results.append(
                f"Mafia убил {server_chat[game_id]['players'][target]}"
            )
        elif role == 'Doctor' and target:
            results.append(
                f"Doctor вылечил {server_chat[game_id]['players'][target]}"
            )
        elif role == 'Sherif' and target:
            results.append(
                f"Sherif арестовал {server_chat[game_id]['players'][target]}"
            )
        else:
            results.append(f"{role} ничего не выбрал")

    text = "🌅 Ночь закончилась\n\n" + "\n".join(results)

    for user_id in server_chat[game_id]['players']:
        await bot.send_message(user_id, text)




@dp.callback_query(F.data.startswith('night.'))
async def night_action(call: CallbackQuery):
    _, game_id, target = call.data.split('.')
    game_id = int(game_id)
    user_id = call.from_user.id

    if server_chat[game_id]['night']['finished']:
        await call.answer("Ночь уже закончилась", show_alert=True)
        return

    user = session.query(Users).filter(Users.tg_id == user_id).first()

    if target == 'none':
        server_chat[game_id]['night']['actions'][user_id] = {
            'role': user.roles,
            'target': None
        }
        await call.answer("Ты ничего не выбрал")
    else:
        target = int(target)
        server_chat[game_id]['night']['actions'][user_id] = {
            'role': user.roles,
            'target': target
        }
        await call.answer("Выбор сохранён")

    await call.message.edit_reply_markup(reply_markup=None)


class Game_id(StatesGroup):
    game_id = State()

"""Joining in game"""

@dp.message(Command('join_game'))
async def join_games(message: Message, state: FSMContext):
    await message.answer('Enter game id')
    await state.set_state(Game_id.game_id)


@dp.message(Game_id.game_id)
async def get_game_id(message: Message, state: FSMContext):
    global server_chat
    if message.text.isdigit():
        r = session.query(Game).filter(Game.id == int(message.text)).first()
        if not r:
            await message.answer('Game not found')
            return
        if r.status != 'waiting':
            await message.answer('Game almost started')
            return
        if r:
            if r.id not in server_chat.keys():
                # В server_chat[game_id] будем хранить:
                server_chat[r.id] = {
                    'chats': {
                        'start_chats': {}
                    },
                    'players': {},          # user_id: username
                    'starting': False,
                    'night': {
                        'actions': {},      # user_id: {'role': role, 'target': user_id | None}
                        'finished': False
                    }
                }

            
            game = r
            markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text='Join game', callback_data=f'start_game.{game.id}')]
            ])
            text = ''
            if server_chat[game.id]['players']:
                text = '\n'.join(
                    v for v in server_chat[game.id]['players'].values())
            mess = await message.answer(f'''Game ID: {game.id}. Wait for some people\n{text}''', reply_markup=markup)
            # server_chat[game.id]['players'][message.from_user.id] = message.from_user.username
            server_chat[game.id]['chats']['start_chats'][message.chat.id] = mess.message_id


async def main():
    try:
        print('Bot run')
        await bot.set_my_commands(command)
        await dp.start_polling(bot)
    except:
        print('Bot stoped')

asyncio.run(main())

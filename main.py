from promt import AI_PROMT_CODE
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
from groq import Groq
# ID of active game, end send all user in game
server_chat: dict[int, dict] = {}
roles = ['Mafia', 'Sherif', 'Doctor', 'Villager', 'Villager', 'Villager',
         'Villager', 'Villager', 'Villager', 'Villager']  # Max 10 users

dp = Dispatcher()
command = [
    BotCommand(command='start', description='Start bot, and registration'),
]
load_dotenv()
TOKEN = os.getenv("TOKEN")  # bot token
TOKEN_GROQ = os.getenv("TOKEN_GROQ")  # bot token
bot = Bot(TOKEN)
client = Groq(api_key=TOKEN_GROQ)
session = sessionmaker(engine)()

'''User registration'''


@dp.message(Command('start'))
async def start(message: Message):
    r = session.query(Users).filter(
        Users.tg_id == message.from_user.id).first()
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='create game', callback_data='create_game'), InlineKeyboardButton(
            text='join game', callback_data='join_game')]
    ])
    if r:
        await message.answer('Select action ❇️:', reply_markup=markup)
    else:
        user = Users(tg_id=message.from_user.id,
                     username=message.from_user.username)
        session.add(user)
        session.commit()
        await message.answer('Welcome. Select action ❇️:', reply_markup=markup)


'''Create game for start playing'''


@dp.callback_query(F.data == 'create_game')
async def create_game(call: CallbackQuery):
    global server_chat
    game = Game(create_by=call.from_user.id)
    session.add(game)
    session.commit()

    # В server_chat[game_id] будем хранить:
    server_chat[game.id] = {
        'created_by': [call.from_user.id, call.from_user.username],
        'chats': {
            'start_chats': {}
        },
        'players': {},          # user_id: username
        'night': {
            'actions': {},      # user_id: {'role': role, 'target': user_id | None}
            'finished': False
        },
        'day': {
            'votes': {},        # voter_id -> target_id
            'finished': False
        },
        'is_day': True
    }

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text='Join game', callback_data=f'start_game.{game.id}')]
    ])

    mess = await call.message.answer(f'''Game ID: {game.id}. Wait for some people''', reply_markup=markup)

    server_chat[game.id]['chats']['start_chats'][mess.chat.id] = mess.message_id


@dp.callback_query(F.data.startswith('start_game.'))
async def join_game(call: CallbackQuery):
    global server_chat

    user = session.query(Users).filter(
        Users.tg_id == call.from_user.id).first()
    game_id = int(call.data.split('.')[1])

    if user.active_game and user.active_game != game_id:
        old_game = user.active_game

        if old_game in server_chat:
            server_chat[old_game]['players'].pop(user.tg_id, None)

        user.active_game = None
        session.commit()

    if game_id not in server_chat or 'players' not in server_chat[game_id]:
        await call.answer("Игра не найдена")
        return

    user_id = call.from_user.id
    username = call.from_user.username
    markup_join = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text='Join game', callback_data=f'start_game.{game_id}')]
    ])
    markup_leave = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text='Leave game', callback_data=f'start_game.{game_id}')]
    ])

    user = session.query(Users).filter(Users.tg_id == user_id).first()
    gameq = session.query(Game).filter(Game.id == game_id).first()

    if user_id in server_chat[game_id]['players']:
        # LEAVE
        del server_chat[game_id]['players'][user_id]
        await call.answer('You left the game')
        user.active_game = None
        gameq.player_count -= 1
        session.commit()
        await call.message.edit_reply_markup(reply_markup=markup_join)
    else:
        # JOIN
        server_chat[game_id]['players'][user_id] = username
        await call.answer('You joined the game')
        user.active_game = game_id
        gameq.player_count += 1
        session.commit()
        await call.message.edit_reply_markup(reply_markup=markup_leave)

    text = f'Game ID: {game_id}. Wait for some people\n' + \
        '\n'.join([name for name in server_chat[game_id]['players'].values()])

    for chat_id, message_id in server_chat[game_id]['chats']['start_chats'].items():
        if chat_id in server_chat[game_id]['players'].keys():
            await bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_id, reply_markup=markup_leave)
        else:
            await bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_id, reply_markup=markup_join)

    markup_start_game = None
    if user_id in server_chat[game_id]['players']:
        markup_start_game = markup_leave
    else:
        markup_start_game = markup_join

    if len(server_chat[game_id]['players']) >= 1:
        markup_start_game.inline_keyboard.append([InlineKeyboardButton(
            text='Start game', callback_data=f'begin_game.{game_id}')])
    elif len(markup_start_game.inline_keyboard) == 2:
        markup_start_game.inline_keyboard.remove([InlineKeyboardButton(
            text='Start game', callback_data=f'begin_game.{game_id}')])

    await bot.edit_message_text(text=text, chat_id=server_chat[game_id]['created_by'][0], message_id=server_chat[game_id]['chats']['start_chats'][server_chat[game_id]['created_by'][0]], reply_markup=markup_start_game)


@dp.callback_query(F.data.startswith('begin_game.'))
async def begin_game(call: CallbackQuery):
    game_id = int(call.data.split('.')[1])

    if game_id not in server_chat:
        return

    players = server_chat[game_id]['players']
    user_len = len(players)

    roleq = roles[:user_len]
    random.shuffle(roleq)

    for user_id, role in zip(players.keys(), roleq):
        user = session.query(Users).filter(Users.tg_id == user_id).first()
        user.roles = role
        user.active_game = game_id
        session.commit()
        await bot.send_message(user_id, f'🎭 Твоя роль: {role}')

    game = session.query(Game).filter(Game.id == game_id).first()
    game.player_count = user_len
    game.status = 'in_game'
    session.commit()

    # 🌙 Ночь
    server_chat[game_id]['is_day'] = False
    server_chat[game_id]['night'] = {
        'actions': {},
        'finished': False
    }

    for user_id in players:
        await bot.send_message(user_id, "🌙 Ночь наступает. Город засыпает...")

    await start_night_phase(game_id)


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
        role_action = ''
        match user.roles:
            case 'Mafia':
                role_action = 'кого убить'
            case 'Sherif':
                role_action = 'кого арестовать'
            case 'Doctor':
                role_action = 'кого вылечить'

        await bot.send_message(
            chat_id=user.tg_id,
            text=f"Твоя роль: {user.roles}\nВыбери {role_action}:",
            reply_markup=markup
        )
    else:
        await bot.send_message(
            chat_id=user.tg_id,
            text=f'Твоя роль: {user.roles}. Ты не можешь ничего выбрать'
        )


async def resolve_night(game_id: int):
    actions = server_chat[game_id]['night']['actions']
    players = server_chat[game_id]['players']

    mafia_target = None
    doctor_target = None
    sherif_target = None
    sherif_id = None
    night_log = []

    for user_id, action in actions.items():
        if action['role'] == 'Mafia':
            mafia_target = action['target']
            if mafia_target:
                night_log.append(f'Mafia нацелился на {players[mafia_target]}')
            else:
                night_log.append('Mafia ничего не выбрала')

        elif action['role'] == 'Doctor':
            doctor_target = action['target']
            if doctor_target:
                night_log.append(
                    f'Doctor собирается вылечить {players[doctor_target]}')
            else:
                night_log.append('Doctor ничего не выбрал')

        elif action['role'] == 'Sherif':
            sherif_target = action['target']
            sherif_id = user_id
            if sherif_target:
                night_log.append(
                    f'Sherif хочет арестовать {players[sherif_target]}')
            else:
                night_log.append('Sherif ничего не выбрал')

    dead_players = set()
    arrested_players = set()
    finile_log = []

    if mafia_target:
        if doctor_target != mafia_target:
            dead_players.add(mafia_target)
            finile_log.append(f'Mafia убил {players[mafia_target]}')
        else:
            finile_log.append(
                f'Mafia попыталась убить {players[mafia_target]}, но Doctor его спас')

    if sherif_target:
        target_role = session.query(Users).filter(
            Users.tg_id == sherif_target).first().roles
        if target_role == 'Mafia' and mafia_target != sherif_id:
            finile_log.append('Sherif арестовал Mafia')
            arrested_players.add(sherif_target)
        elif target_role == 'Mafia' or mafia_target == sherif_id:
            dead_players.add(sherif_id)
            finile_log.append(
                "Sherif нашёл Mafia но не успел арестовать, он умер")
        else:
            arrested_players.add(sherif_target)
            finile_log.append(f'Sherif арестовал {players[sherif_target]}')

    eliminated = dead_players | arrested_players

    for uid in eliminated:
        role = session.query(Users).filter(Users.tg_id == uid).first().roles
        finile_log.append(f"❌ {players[uid]} ({role}) выбыл")

    if not night_log:
        text = "🌅 Ночь прошла спокойно. Никто не выбыл."
    else:
        text = "🌅 Что собирались делать этой ночю:\n\n" + "\n".join(night_log)
        text2 = 'Итоги ночи:\n\n' + '\n'.join(finile_log)

    for uid in server_chat[game_id]['players']:
        await bot.send_message(uid, text)
        await bot.send_message(uid, text2)

    for uid in eliminated:
        if uid in server_chat[game_id]['players']:
            del server_chat[game_id]['players'][uid]

        user = session.query(Users).filter(Users.tg_id == uid).first()
        user.active_game = None
        user.roles = None
        session.commit()

        if await check_game_end(game_id):
            return

        server_chat[game_id]['is_day'] = True
        server_chat[game_id]['day'] = {
            'votes': {},
            'finished': False
        }
        
        await start_day_phase(game_id)

async def start_day_phase(game_id: int):
    players = server_chat[game_id]['players']

    for voter_id in players:
        buttons = []

        for target_id, username in players.items():
            if target_id == voter_id:
                continue
            buttons.append([
                InlineKeyboardButton(
                    text=username,
                    callback_data=f"dayvote.{game_id}.{target_id}"
                )
            ])

        markup = InlineKeyboardMarkup(inline_keyboard=buttons)

        await bot.send_message(
            voter_id,
            "☀️ День наступил. Выбери, кого повесить:",
            reply_markup=markup
        )

    await asyncio.sleep(40)

    if not server_chat[game_id]['day']['finished']:
        await resolve_day(game_id)

async def resolve_day(game_id: int):
    day = server_chat[game_id]['day']
    players = server_chat[game_id]['players']

    day['finished'] = True

    votes = {}
    for target in day['votes'].values():
        votes[target] = votes.get(target, 0) + 1

    if not votes:
        for uid in players:
            await bot.send_message(uid, "☀️ Никто не проголосовал. День прошёл спокойно.")
        return

    max_votes = max(votes.values())
    leaders = [uid for uid, v in votes.items() if v == max_votes]

    if len(leaders) > 1:
        for uid in players:
            await bot.send_message(uid, "⚖️ Голоса разделились. Никто не был повешен.")
        return

    eliminated = leaders[0]
    role = session.query(Users).filter(Users.tg_id == eliminated).first().roles

    for uid in players:
        await bot.send_message(
            uid,
            f"❌ {players[eliminated]} был повешен.\nЕго роль: {role}"
        )

    players.pop(eliminated)

    user = session.query(Users).filter(Users.tg_id == eliminated).first()
    user.active_game = None
    user.roles = None
    session.commit()

    if await check_game_end(game_id):
        return

    server_chat[game_id]['is_day'] = False
    server_chat[game_id]['night'] = {
        'actions': {},
        'finished': False
    }

    await start_night_phase(game_id)

@dp.callback_query(F.data.startswith('dayvote.'))
async def day_vote(call: CallbackQuery):
    _, game_id, target_id = call.data.split('.')
    game_id = int(game_id)
    target_id = int(target_id)
    voter_id = call.from_user.id

    day = server_chat[game_id]['day']

    if day['finished']:
        await call.answer("Голосование окончено", show_alert=True)
        await call.message.edit_reply_markup(reply_markup=None)
        return

    day['votes'][voter_id] = target_id
    await call.answer("Голос принят")


    if len(day['votes']) == len(server_chat[game_id]['players']):
        await resolve_day(game_id)


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


async def check_game_end(game_id: int):
    if game_id not in server_chat:
        return True

    players = server_chat[game_id]['players']
    user_objs = session.query(Users).filter(Users.tg_id.in_(players.keys())).all()
    roles_left = [u.roles for u in user_objs]

    if len(players) == 2:
        if 'Mafia' in roles_left and 'Sherif' in roles_left:
            for uid in players:
                await bot.send_message(uid, "🤝 Ничья! Остались Mafia и Sherif.")
            await finish_game(game_id)
            return True

        if 'Mafia' in roles_left:
            for uid in players:
                await bot.send_message(uid, "😈 Победа Mafia!")
            await finish_game(game_id)
            return True

    if 'Mafia' not in roles_left and len(players) > 2:
        for uid in players:
            await bot.send_message(uid, "🎉 Победа мирных! Mafia уничтожена.")
        await finish_game(game_id)
        return True

    return False


async def finish_game(game_id: int):
    players = server_chat[game_id]['players']

    for uid in players:
        user = session.query(Users).filter(Users.tg_id == uid).first()
        user.active_game = None
        user.roles = None
        session.commit()

    game = session.query(Game).filter(Game.id == game_id).first()
    if game:
        session.delete(game)
        session.commit()

    del server_chat[game_id]


"""Joining in game"""


@dp.callback_query(F.data == 'join_game')
async def join_games(call: CallbackQuery):
    r = session.query(Game).filter(Game.status == 'waiting').all()

    markup = InlineKeyboardMarkup(inline_keyboard=[])
    for i in r:
        if i.id in server_chat.items():
            markup.inline_keyboard.append([InlineKeyboardButton(
                text=f'{i.id} by {server_chat[i.id]['created_by'][1]}', callback_data=f'join.{i.id}')])
        else:
            user = session.query(Users).filter(Users.tg_id == i.create_by).first()
            markup.inline_keyboard.append([InlineKeyboardButton(
                text=f'{i.id} by {user.username}', callback_data=f'join.{i.id}')])
    await call.message.answer('All active games:\n\n', reply_markup=markup)


@dp.callback_query(F.data.startswith('join.'))
async def get_game_id(call: CallbackQuery):
    global server_chat
    id_of_game = int(call.data.split(".")[1])
    if id_of_game:
        r = session.query(Game).filter(Game.id == id_of_game).first()
        creted_user = session.query(Users).filter(
            Users.tg_id == r.create_by).first()
        if not r:
            await call.message.answer('Game not found')
            return
        if r.status != 'waiting':
            await call.message.answer('Game almost started')
            return
        if r:
            if r.id not in server_chat.keys():
                # В server_chat[game_id] будем хранить:
                server_chat[r.id] = {
                    'created_by': [creted_user.tg_id, creted_user.username],
                    'chats': {
                        'start_chats': {}
                    },
                    'players': {},          # user_id: username
                    'night': {
                        'actions': {},      # user_id: {'role': role, 'target': user_id | None}
                        'finished': False
                    },
                    'day': {
                        'votes': {},        # voter_id -> target_id
                        'finished': False
                    },

                    'is_day': True
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
            mess = await call.message.answer(f'''Game ID: {game.id}. Wait for some people\n{text}''', reply_markup=markup)
            # server_chat[game.id]['players'][message.from_user.id] = message.from_user.username
            server_chat[game.id]['chats']['start_chats'][mess.chat.id] = mess.message_id


@dp.message()
async def groq(message: Message):
    user = session.query(Users).filter(
        Users.tg_id == message.from_user.id).first()

    if not user.active_game:
        try:
            action = client.chat.completions.create(
                model='openai/gpt-oss-120b',
                messages=[
                    {
                        'role': 'system',
                        'content': f'Ты помощник по игре Mafia. Объясняй правила, роли и механику. Не отвечай практически ни на какие сообщение, если они не связаны с игрой в мафией. Вот исходный код, правила рассказывай относительно этого кода(не говори про регистрацию и прочее под копотом) ещё раз говорю, не рассказывай код, рассказывай правила, а не код, и пиши максимольно коротко, очень предложений 1-3 достаточно: {AI_PROMT_CODE}'
                    },
                    {'role': 'user', 'content': message.text}
                ],
                max_tokens=500
            )
            await message.answer(action.choices[0].message.content)
        except Exception as e:
            print(e)
        return

    game_id = user.active_game

    if game_id not in server_chat:
        return

    game = server_chat[game_id]

    if not game['is_day']:
        return

    for uid in game['players']:
        if uid != message.from_user.id:
            await bot.send_message(uid, f"{message.from_user.username}: {message.text}")

    players = ', '.join(game['players'].values())
    players_id = game['players']

    random_AI = random.randint(1, 8)
    if random_AI == 3:
        try:
            action = client.chat.completions.create(
                model='openai/gpt-oss-120b',
                messages=[
                    {
                        'role': 'system',
                        'content': (
                            'Ты игрок в Mafia. Веди себя как человек. '
                            'Подозревай игроков, анализируй, но не раскрывай роли.\n'
                            f'Игроки: [{players}].'
                            'Пиши что то по типу: "Я думаю это ..." или "Я подозреваю ..., я считаю что он Мафия", это лишь пример, но тебе нужно делать что то по типу этого'
                        )
                    },
                    {'role': 'user', 'content': message.text}
                ],
                max_tokens=100
            )
        except Exception as e:
            print(e)
        for k in players_id.keys():
            await bot.send_message(text=f'GPT: {action.choices[0].message.content}', chat_id=k)



    if 'Bot' not in message.text or 'GPT' not in message.text:
        return
    try:
        action = client.chat.completions.create(
            model='openai/gpt-oss-120b',
            messages=[
                {
                    'role': 'system',
                    'content': (
                        'Ты игрок в Mafia. Веди себя как человек. '
                        'Подозревай игроков, анализируй, но не раскрывай роли.\n'
                        f'Игроки: [{players}]'
                        f'Вот исходный код, правила рассказывай относительно этого кода(не говори про регистрацию и прочее под копотом) ещё раз говорю, не рассказывай код, рассказывай правила, а не код, и пиши максимольно коротко, очень предложений 1-3 достаточно: {AI_PROMT_CODE}'
                    )
                },
                {'role': 'user', 'content': message.text}
            ],
            max_tokens=100
        )
    except Exception as e:
        print(e)
    for k in players_id.keys():
        await bot.send_message(text=f'GPT: {action.choices[0].message.content}', chat_id=k)


async def main():
    try:
        print('Bot run')
        await bot.set_my_commands(command)
        await dp.start_polling(bot)
    except Exception as e:
        print('Bot stoped\n', e)

asyncio.run(main())

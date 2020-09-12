import os
import logging
import threading
from enum import Enum

import numpy as np
import telegram.error
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Updater, CommandHandler, MessageHandler, CallbackQueryHandler, Filters


fmt = '%Y-%m-%d %H:%M:%S'
token = os.getenv('THE_HAT_GAME_BOT_API_TOKEN')
admin_id = int(os.getenv('TELEGRAM_ADMIN_ID'))
game_chat_id = int(os.getenv('TELEGRAM_THE_HAT_GAME_CHAT_ID'))

n_words_per_player = 6
time_per_player = 60

GAME_STATE = Enum('GAME_STATE', ['IDLE', 'PREPARATION', 'ALIAS', 'COW', 'ONE_WORD'])
PLAYER_STATE = Enum('PLAYER_STATE', ['ADDING', 'READY'])
ROUND_NAMES = {GAME_STATE.ALIAS: 'Alias',
               GAME_STATE.COW: 'Charades',
               GAME_STATE.ONE_WORD: 'Explain by a single word'}


class Hat():
    __hat = None

    @staticmethod
    def hat():
        if Hat.__hat is None:
            Hat()
        return Hat.__hat

    def __init__(self):
        if Hat.__hat is not None:
            raise Exception("This class is a singleton!")
        else:
            Hat.__hat = self

            self.game_state = GAME_STATE.IDLE
            self.ready_for_the_next_round = False
            self.user_round_stopped = False

            self.players = []
            self.player_state = {}
            self.player_words = {}
            self.words = []

            self.team_names = ['Team Manhattan', 'Team Brooklyn']
            self.teams = [[], []]
            self.player_pointers = [0, 0]
            self.team_pointer = 0

            self.guess_counter = 0
            self.discard_counter = 0
            self.team_scores = [0, 0]

            self.word_pointer = 0

            self.query = None
            self.last_msg = None


def error(update, context):
    logging.getLogger(__name__).warning('Update "%s" caused error "%s"', update, context.error)
    try:
        raise context.error
    except telegram.error.Unauthorized:
        # remove update.message.user_id from conversation list
        pass
    except telegram.error.BadRequest:
        # handle malformed requests - read more below!
        pass
    except telegram.error.TimedOut:
        # handle slow connection problems
        pass
    except telegram.error.NetworkError:
        # handle other connection problems
        pass
    except telegram.error.ChatMigrated:
        # the user_id of a group has changed, use e.new_user_id instead
        pass
    except telegram.error.TelegramError:
        # handle all other telegram related errors
        pass


def get_user_name(user):
    user_name = user.first_name
    if user.last_name:
        user_name += ' ' + user.last_name
    user_name = user_name.strip(':')
    return user_name


def all_players_are_ready():
    hat = Hat.hat()
    for _, state in hat.player_state.items():
        if state != PLAYER_STATE.READY:
            return False
    return True


def make_teams():
    hat = Hat.hat()
    n_players = len(hat.players)
    permutation = np.random.permutation(n_players)
    hat.teams[0] = hat.players[permutation[:(n_players+1) // 2]]
    hat.teams[1] = hat.players[permutation[(n_players+1) // 2:]]


def next_word(update, context):
    hat = Hat.hat()
    hat.query = update.callback_query
    hat.query.answer()
    user_id = update.effective_user.id
    hat.query.edit_message_reply_markup(None)
    query_type = int(hat.query.data)

    yes = InlineKeyboardButton('✔️', callback_data='1')
    no = InlineKeyboardButton('❌', callback_data='2')
    keyboard = [[yes, no]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query_type == 0:
        hat.user_round_stopped = False
        context.bot.send_message(chat_id=game_chat_id, text='{} started their round.'.format(get_user_name(update.effective_user)))
        threading.Timer(time_per_player, stop_user_round, [update, context, True]).start()
    elif query_type == 1:
        hat.team_scores[hat.team_pointer] += 1
        hat.guess_counter += 1
    elif query_type == 2:
        hat.discard_counter += 1

    if hat.word_pointer < len(hat.words):
        hat.last_msg = context.bot.send_message(chat_id=user_id, text=hat.words[hat.word_pointer], reply_markup=reply_markup)
        hat.word_pointer += 1
    else:
        stop_user_round(update, context)


def start_user_round(context, player):
    hat = Hat.hat()
    context.bot.send_message(chat_id=game_chat_id, text="It is {}'s and {} turn now.".format(get_user_name(player), hat.team_names[hat.team_pointer]))

    words_in_queue = hat.words[hat.word_pointer:]
    permutation = np.random.permutation(len(words_in_queue))
    words_in_queue = words_in_queue[permutation]
    hat.words[hat.word_pointer:] = words_in_queue
    hat.guess_counter = 0
    hat.discard_counter = 0

    ready = InlineKeyboardButton('START!', callback_data=0)
    keyboard = [[ready]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    context.bot.send_message(chat_id=player.id, text='Press START when you are ready.', reply_markup=reply_markup)


def stop_user_round(update, context, time_is_up=False):
    hat = Hat.hat()
    if not hat.user_round_stopped:
        if time_is_up:
            print('time is up')
        hat.user_round_stopped = True
        user_id = update.effective_user.id

        if time_is_up:
            hat.last_msg.edit_reply_markup(reply_markup=None)
            context.bot.send_message(chat_id=user_id, text='Your time is up.', reply_markup=ReplyKeyboardRemove())
        else:
            context.bot.send_message(chat_id=user_id, text='No words left.')

        current_player = hat.teams[hat.team_pointer][hat.player_pointers[hat.team_pointer]]
        ending1 = '' if hat.guess_counter == 1 else 's'
        ending2 = '' if hat.discard_counter == 1 else 's'
        context.bot.send_message(chat_id=game_chat_id, text='{} finished their round.\n{} word{} guessed, {} word{} discarded.'.format(get_user_name(current_player), hat.guess_counter, ending1, hat.discard_counter, ending2))
        # context.bot.send_message(chat_id=game_chat_id, text='{} score: {}'.format(hat.team_names[hat.team_pointer], hat.team_scores[hat.team_pointer]))

        hat.team_pointer = 1 - hat.team_pointer
        hat.player_pointers[hat.team_pointer] += 1
        if hat.player_pointers[hat.team_pointer] == len(hat.teams[hat.team_pointer]):
            hat.player_pointers[hat.team_pointer] = 0

        if hat.word_pointer != hat.words.size:
            next_player = hat.teams[hat.team_pointer][hat.player_pointers[hat.team_pointer]]
            start_user_round(context, next_player)
        else:
            context.bot.send_message(chat_id=game_chat_id, text='Round ended')
            hat.ready_for_the_next_round = True

            if hat.game_state == GAME_STATE.ONE_WORD:
                context.bot.send_message(chat_id=game_chat_id, text='GAME OVER!\n{} {}: {} {}'.format(hat.team_names[0], hat.team_scores[0], hat.team_scores[1], hat.team_names[1]))
                hat.game_state = GAME_STATE.IDLE


def start(update, context):
    hat = Hat.hat()
    chat_id = update.effective_chat.id
    if chat_id != game_chat_id:
        context.bot.send_message(chat_id=chat_id, text='The game can be started in the main chat. To join the already started game send /join command.')
    elif hat.game_state != GAME_STATE.IDLE:
        context.bot.send_message(chat_id=chat_id, text='The game has already started.')
    else:
        hat.game_state = GAME_STATE.PREPARATION
        hat.players = []
        hat.player_state = {}
        hat.player_words = {}
        hat.words = []
        context.bot.send_message(chat_id=game_chat_id, text='GAME IS STARTING! Players, please, join the game!')


def join(update, context):
    hat = Hat.hat()
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if hat.game_state != GAME_STATE.PREPARATION:
        context.bot.send_message(chat_id=chat_id, text='You were late, wait till the next game.')
    elif user_id in hat.player_state:
        context.bot.send_message(chat_id=chat_id, text='You are already in the game.')
    else:
        hat.players.append(update.effective_user)
        hat.player_state[user_id] = PLAYER_STATE.ADDING
        hat.player_words[user_id] = 0
        hat.ready_for_the_next_round = False
        context.bot.send_message(chat_id=game_chat_id, text='{} joined the game. Welcome!'.format(get_user_name(update.effective_user)))
        context.bot.send_message(chat_id=user_id, text='Enter {} characters (real, fictional, historical, etc.), one per message.'.format(n_words_per_player))


def add_word(update, context):
    hat = Hat.hat()
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if hat.game_state != GAME_STATE.PREPARATION:
        context.bot.send_message(chat_id=chat_id, text='You cannot add words now.')
    elif chat_id != user_id:
        context.bot.send_message(chat_id=chat_id, text='Please, add words in a private chat.')
    elif user_id not in hat.player_state:
        context.bot.send_message(chat_id=chat_id, text='Please, join the game first.')
    elif hat.player_state[user_id] == PLAYER_STATE.READY:
        context.bot.send_message(chat_id=chat_id, text='Enough!')
    else:
        hat.words.append(update.message.text)
        hat.player_words[user_id] += 1
        if hat.player_words[user_id] == n_words_per_player:
            hat.player_state[user_id] = PLAYER_STATE.READY
            context.bot.send_message(chat_id=chat_id, text='Got it!')
            context.bot.send_message(chat_id=game_chat_id, text='{} is ready'.format(get_user_name(update.effective_user)))
            if all_players_are_ready():
                hat.ready_for_the_next_round = True
                player_names = [get_user_name(player) for player in hat.players]
                context.bot.send_message(chat_id=game_chat_id, text='Everyone is ready. Welcome {}. Number of players: {}'.format(', '.join(player_names), len(hat.players)))


def next_round(update, context):
    hat = Hat.hat()
    chat_id = update.effective_chat.id
    # user_id = update.effective_user.id
    if chat_id != game_chat_id:
        context.bot.send_message(chat_id=chat_id, text='This has to be done in the game chat.')
    elif not hat.ready_for_the_next_round:
        context.bot.send_message(chat_id=chat_id, text='The current round is not over yet.')
    else:
        if hat.game_state == GAME_STATE.PREPARATION:
            hat.players = np.asarray(hat.players)
            hat.words = np.asarray(hat.words)
            make_teams()
            team0_names = [get_user_name(player) for player in hat.teams[0]]
            team1_names = [get_user_name(player) for player in hat.teams[1]]
            context.bot.send_message(chat_id=game_chat_id, text='Welcome {}: {}.\nWelcome {}: {}.'.format(hat.team_names[0], ', '.join(team0_names), hat.team_names[1], ', '.join(team1_names)))

        if hat.game_state in ROUND_NAMES:
            context.bot.send_message(chat_id=game_chat_id, text='{} {}: {} {}'.format(hat.team_names[0], hat.team_scores[0], hat.team_scores[1], hat.team_names[1]))
        hat.game_state = GAME_STATE(hat.game_state.value + 1)
        if hat.game_state in ROUND_NAMES:
            context.bot.send_message(chat_id=game_chat_id, text='Starting round "{}".'.format(ROUND_NAMES[hat.game_state]))

        permutation = np.random.permutation(len(hat.words))
        hat.words = hat.words[permutation]
        hat.word_pointer = 0

        next_player = hat.teams[hat.team_pointer][hat.player_pointers[hat.team_pointer]]
        start_user_round(context, next_player)


def reset(update, context):
    hat = Hat.hat()
    user_id = update.effective_user.id
    if user_id == admin_id:
        hat.game_state = GAME_STATE.IDLE
        hat.players = []
        hat.player_words = {}
        hat.words = []


def echo(update, context):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if user_id == admin_id:
        print('chat_id: {}\nuser_id: {}'.format(chat_id, user_id))


def main():
    # set up logging
    logging.basicConfig(filename='hat.log', level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # bot API
    updater = Updater(token, use_context=True)
    dispatcher = updater.dispatcher

    # bot commands
    dispatcher.add_handler(CommandHandler('start', start))
    dispatcher.add_handler(CommandHandler('join', join))
    dispatcher.add_handler(CommandHandler('next', next_round))
    dispatcher.add_handler(CommandHandler('reset', reset))
    dispatcher.add_handler(CommandHandler('echo', echo))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, add_word))

    dispatcher.add_handler(CallbackQueryHandler(next_word))
    dispatcher.add_error_handler(error)

    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()

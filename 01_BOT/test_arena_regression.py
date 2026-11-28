"""Offline regression tests for the actual arena handler and XP functions."""
import ast
import asyncio
import logging
import secrets
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from lumi_database_vault import connect_private
from lumi_economy import eligible_for_reward, pair_battles_today


class FakeTelegramError(Exception):
    pass


class ArenaRegressionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / 'arena.sqlite'
        self.connect = lambda: connect_private(path, timeout=5)
        tree = ast.parse(Path(__file__).with_name('bot.py').read_text(encoding='utf-8'))
        names = {'arena_resolve', 'arena_get', 'arena_add_xp', 'arena_need',
                 'arena_award', 'arena_season', 'arena_power', 'is_match'}
        nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
        self.assertEqual({n.name for n in nodes}, names)
        for n in nodes:
            n.decorator_list = []
            n.returns = None
            for a in n.args.args:
                a.annotation = None
        self.ns = dict(asyncio=asyncio, connect_db=self.connect,
                       eligible_for_reward=eligible_for_reward, pair_battles_today=pair_battles_today,
                       datetime=datetime, timezone=timezone, secrets=secrets,
                       ARENA_HEROES=[('Hero A',), ('Hero B',)],
                       TelegramAPIError=FakeTelegramError, logger=logging.getLogger(__name__))
        # Only selected trusted local functions; no bot startup, token or network.
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'bot.py', 'exec'), self.ns)  # nosec B102
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE profiles(user_id INTEGER PRIMARY KEY, age INTEGER);
                INSERT INTO profiles VALUES(1,20),(2,21),(3,22);
                CREATE TABLE account_suspensions(user_id INTEGER, expires_at TEXT);
                CREATE TABLE reactions(from_user INTEGER,to_user INTEGER,liked INTEGER);
                INSERT INTO reactions VALUES(1,2,1),(2,1,1);
                CREATE TABLE blocks(user_id INTEGER,blocked_id INTEGER);
                CREATE TABLE arena_heroes(user_id INTEGER PRIMARY KEY,hero_id INTEGER NOT NULL,
                  level INTEGER DEFAULT 1,xp INTEGER DEFAULT 0,rating INTEGER DEFAULT 0,
                  wins INTEGER DEFAULT 0,losses INTEGER DEFAULT 0,draws INTEGER DEFAULT 0,last_daily TEXT);
                INSERT INTO arena_heroes(user_id,hero_id) VALUES(1,1),(2,2);
                CREATE TABLE arena_collection(user_id INTEGER,hero_id INTEGER,level INTEGER DEFAULT 1,
                  xp INTEGER DEFAULT 0,PRIMARY KEY(user_id,hero_id));
                CREATE TABLE arena_account_progress(user_id INTEGER PRIMARY KEY,total_xp INTEGER CHECK(total_xp>=0));
                CREATE TABLE arena_achievements(user_id INTEGER,code TEXT,PRIMARY KEY(user_id,code));
                CREATE TABLE arena_challenges(id INTEGER PRIMARY KEY,challenger INTEGER,defender INTEGER,
                  status TEXT DEFAULT 'pending',created_at TEXT DEFAULT CURRENT_TIMESTAMP,resolved_at TEXT);
                INSERT INTO arena_challenges(id,challenger,defender) VALUES(1,1,2);
                CREATE TABLE arena_battle_log(id INTEGER PRIMARY KEY,challenge_id INTEGER UNIQUE,
                  winner INTEGER,loser INTEGER,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE arena_season_scores(season TEXT,user_id INTEGER,wins INTEGER,points INTEGER,
                  PRIMARY KEY(season,user_id));
            ''')

    def callback(self, uid=2):
        return SimpleNamespace(data='arena:accept:1', from_user=SimpleNamespace(id=uid),
                               answer=AsyncMock(), message=SimpleNamespace(edit_reply_markup=AsyncMock()),
                               bot=SimpleNamespace(send_message=AsyncMock()))

    async def resolve(self, callback):
        await self.ns['arena_resolve'](callback)

    def verify_single_reward(self):
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT status FROM arena_challenges').fetchone()[0], 'completed')
            battles = db.execute('SELECT winner,loser FROM arena_battle_log').fetchall()
            self.assertEqual(len(battles), 1)
            winner, loser = battles[0]
            self.assertEqual({winner, loser}, {1, 2})
            self.assertEqual(dict(db.execute('SELECT user_id,total_xp FROM arena_account_progress')), {winner:40, loser:10})
            self.assertEqual(dict(db.execute('SELECT user_id,xp FROM arena_collection')), {winner:40, loser:10})
            self.assertEqual(db.execute('SELECT user_id,xp,rating,wins,losses FROM arena_heroes ORDER BY user_id').fetchall(),
                             sorted([(winner,40,30,1,0),(loser,10,0,0,1)]))
            self.assertEqual(db.execute('SELECT user_id,wins,points FROM arena_season_scores').fetchall(), [(winner,1,30)])

    async def test_notifies_both_players(self):
        cb = self.callback()
        await self.resolve(cb)
        self.assertEqual(sorted(c.args[0] for c in cb.bot.send_message.await_args_list), [1,2])
        self.verify_single_reward()

    async def test_replay_does_not_award_again(self):
        await self.resolve(self.callback())
        replay = self.callback()
        await self.resolve(replay)
        replay.bot.send_message.assert_not_awaited()
        self.assertTrue(replay.answer.await_args.kwargs['show_alert'])
        self.verify_single_reward()

    async def test_concurrent_accept_awards_once(self):
        a, b = self.callback(), self.callback()
        await asyncio.gather(self.resolve(a), self.resolve(b))
        self.assertEqual(sorted([a.bot.send_message.await_count, b.bot.send_message.await_count]), [0,2])
        self.verify_single_reward()

    async def test_wrong_user_cannot_accept(self):
        cb = self.callback(3)
        await self.resolve(cb)
        cb.bot.send_message.assert_not_awaited()
        self.assertTrue(cb.answer.await_args.kwargs['show_alert'])
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT status FROM arena_challenges').fetchone()[0], 'pending')
            self.assertEqual(db.execute('SELECT count(*) FROM arena_account_progress').fetchone()[0], 0)

    async def test_notification_failure_does_not_duplicate_reward(self):
        cb = self.callback()
        cb.bot.send_message.side_effect = [FakeTelegramError(), None]
        await self.resolve(cb)
        self.assertEqual(cb.bot.send_message.await_count, 2)
        await self.resolve(self.callback())
        self.verify_single_reward()

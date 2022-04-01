import json
import time
import config
import threading
from threading import Lock
import sqlite3
import datetime
from binance import Client
import websockets
import asyncio
import pandas as pd

con = sqlite3.connect("klines.db")
cur = con.cursor()
client = Client(config.api_key, config.api_secret_key)
threadLock = threading.Lock()

class technical_indicator:
    def __init__(self, pair):
        self.pair = pair
        self.con = sqlite3.connect("klines.db")
        self.klines = pd.read_sql_query("SELECT closing FROM {pair}".format(pair = pair), self.con)

    def ema(self, rate):
        ema = self.klines.ewm(span=rate, adjust=False).mean()
        return ema.iloc[-1]

    def update(self):
        self.klines = pd.read_sql_query("SELECT closing FROM {pair}".format(pair = self.pair), self.con)
        while self.klines.isnull().values.any() == True:
            self.klines = pd.read_sql_query("SELECT closing FROM {pair}".format(pair = self.pair), self.con)
            time.sleep(1)
        
class trading_bot:
    def __init__(self, pair):
        self.pair = pair
        self.bought = False
        self.bought_add = 0
        self.time_out = 0
        self.con = sqlite3.connect("klines.db", check_same_thread=False)
        self.cur = self.con.cursor()
        self.klines = pd.read_sql_query("SELECT closing FROM {pair}".format(pair = self.pair), self.con)
        self.thread = threading.Thread(target=self.strategy)
        self.thread.start()

    def strategy(self):
        indicators = technical_indicator(self.pair)
        while True:
            indicators.update()
            time.sleep(1)

    def get_percentage(self, f_value, s_value):
        difference = f_value - s_value
        percentage = difference / s_value * 100
        return percentage

    def take_profit(self):
        if self.bought_add != 0:
                if self.get_percentage(float(self.klines['closing'].iloc[-1]), float(self.bought_add)) >= config.take_profit:
                    self.bought = False
                    self.cur.execute("INSERT INTO profits (symbol, profit) VALUES (?, ?)", (self.pair, self.get_percentage(float(self.klines['closing'].iloc[-1]), self.bought_add)))
                    self.con.commit()
                    self.bought_add = 0

    def stop_loss(self):
        if self.bought_add != 0:
                if self.get_percentage(float(self.klines['closing'].iloc[-1]), float(self.bought_add)) >= -1 * (config.stop_loss):
                    self.bought = False
                    self.cur.execute("INSERT INTO profits (symbol, profit) VALUES (?, ?)", (self.pair, self.get_percentage(float(self.klines['closing'].iloc[-1]), self.bought_add)))
                    self.con.commit()
                    self.bought_add = 0

    def logger(self):
        pass

async def main(symbol_list):
    async with websockets.connect("wss://stream.binance.com:9443/ws") as websocket:
        await websocket.send(json.dumps(
                {
                    "method": "SUBSCRIBE",
                    "params": symbol_list,
                    "id": 1,
                }
            ))

        global a
        while True:   
            msg = await websocket.recv()
            res = json.loads(msg)
            if 'e' in res:
                sql_update(res['k'], res['s'])

def sql_reorganization(symbol):
    global client
    cur.execute("DROP TABLE IF EXISTS {symbol}".format(symbol = symbol))
    cur.execute("CREATE TABLE {symbol} (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol REAL, otime TEXT, ctime TEXT, opening REAL, closing REAL, high REAL, low REAL)".format(symbol = symbol))

    for kline in client.get_historical_klines(symbol, Client.KLINE_INTERVAL_1MINUTE, "4 hour ago UTC"):
        cur.execute("INSERT INTO {symbol} (symbol, otime, ctime, opening, closing, high, low) VALUES (?, ?, ?, ?, ?, ?, ?)".format(symbol = symbol), (symbol, kline[0], kline[6], float(kline[1]), float(kline[4]), float(kline[2]), float(kline[3])))
        con.commit()

def sql_update(res, symbol):
    if res['x'] == True:
        orig = datetime.datetime.fromtimestamp(res['t'] / 1000)
        new = orig + datetime.timedelta(minutes=1)
        newKline = int(new.timestamp() * 1000)
        cur.execute("UPDATE {symbol} set symbol = ?, otime = ?, ctime = ?, opening = ?, closing = ?, high = ?, low = ? WHERE otime = ?".format(symbol = symbol), (symbol, res['t'], res['T'], res['o'], res['c'], res['h'], res['l'], res['t']))
        cur.execute("INSERT INTO {symbol} (symbol, otime) VALUES (?, ?)".format(symbol = symbol), (symbol, int(newKline)))
        con.commit()
    else:
        cur.execute("UPDATE {symbol} set symbol = ?, otime = ?, ctime = ?, opening = ?, closing = ?, high = ?, low = ? WHERE otime = ?".format(symbol = symbol), (symbol, res['t'], res['T'], res['o'], res['c'], res['h'], res['l'], res['t']))
        con.commit()

if __name__ == "__main__":
    bots = []
    pair_list = []

    cur.execute("CREATE TABLE IF NOT EXISTS profits (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, profit REAL)")
    cur.execute("DROP TABLE IF EXISTS profits")
    con.commit()

    for pair in config.pairs:
        sql_reorganization(pair)
        pair_list.append(f"{pair.lower()}@kline_{config.kline_interval}")
        bots.append(trading_bot(pair))

    asyncio.run(main(pair_list))

  
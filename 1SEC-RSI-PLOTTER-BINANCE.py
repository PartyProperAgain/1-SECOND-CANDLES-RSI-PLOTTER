import os
import pandas as pd
import matplotlib.pyplot as plt
from binance.client import Client
from binance import ThreadedWebsocketManager
from datetime import datetime
import threading
import queue
import signal
import logging
from dotenv import load_dotenv

class BinanceRSITraderInitial50:
    def __init__(self, symbol, rsi_window, data_points, api_key, api_secret):
        self.symbol = symbol
        self.rsi_window = rsi_window
        self.data_points = data_points
        self.api_key = api_key
        self.api_secret = api_secret
        self.client = Client(api_key, api_secret)
        self.trade_queue = queue.Queue()
        self.plot_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.close_prices = []
        self.rsi_values = [50] * (rsi_window + 1)  # Start with a default RSI value of 50
        self.times = [datetime.now()] * (rsi_window + 1)  # Initialize times with current time

        self.setup_logging()

    def setup_logging(self):
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)

    def calculate_rsi_optimized(self, close_prices):
        if len(close_prices) < self.rsi_window + 1:
            return 50  # Return an RSI value of 50 until we have enough data points

        delta = close_prices[-1] - close_prices[-2]
        gain = max(delta, 0)
        loss = abs(min(delta, 0))

        if len(self.rsi_values) == self.rsi_window + 1:
            self.avg_gain = sum([max(close_prices[i] - close_prices[i - 1], 0) for i in range(1, self.rsi_window + 1)]) / self.rsi_window
            self.avg_loss = sum([abs(min(close_prices[i] - close_prices[i - 1], 0)) for i in range(1, self.rsi_window + 1)]) / self.rsi_window
        else:
            self.avg_gain = (self.avg_gain * (self.rsi_window - 1) + gain) / self.rsi_window
            self.avg_loss = (self.avg_loss * (self.rsi_window - 1) + loss) / self.rsi_window

        rs = self.avg_gain / self.avg_loss if self.avg_loss != 0 else 0
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def process_trade_message(self, msg):
        try:
            execution_time = datetime.fromtimestamp(msg['T'] / 1000.0)
            price = float(msg['p'])
            self.trade_queue.put((execution_time, price))
        except Exception as e:
            self.logger.error(f"Error processing trade message: {e}")

    def start_trade_stream(self):
        twm = ThreadedWebsocketManager(api_key=self.api_key, api_secret=self.api_secret)
        twm.start()
        twm.start_trade_socket(callback=self.process_trade_message, symbol=self.symbol)
        self.logger.info("Trade stream started")
        self.stop_event.wait()
        twm.stop()

    def aggregate_trades_to_candles(self):
        current_second = None
        last_price = None

        while not self.stop_event.is_set() or not self.trade_queue.empty():
            try:
                timestamp, price = self.trade_queue.get(timeout=1)  # 1-second timeout
                second_start = timestamp.replace(microsecond=0)

                if current_second is None:
                    current_second = second_start

                if second_start > current_second:
                    if last_price is not None:
                        self.plot_queue.put((current_second, last_price))

                    current_second = second_start

                last_price = price
            except queue.Empty:
                continue
            except Exception as e:
                self.logger.error(f"Error aggregating trades: {e}")

    def update_plot(self, ax, line):
        while not self.stop_event.is_set() or not self.plot_queue.empty():
            try:
                timestamp, price = self.plot_queue.get(timeout=1)  # 1-second timeout
                self.times.append(timestamp)
                self.close_prices.append(price)
                rsi = self.calculate_rsi_optimized(self.close_prices)
                if rsi is not None:
                    self.rsi_values.append(rsi)

                    # Ensure the lengths of times and rsi_values match
                    min_length = min(len(self.times), len(self.rsi_values))
                    self.times = self.times[-min_length:]
                    self.rsi_values = self.rsi_values[-min_length:]

                    # Update the line data for plotting
                    line.set_xdata(self.times)
                    line.set_ydata(self.rsi_values)

                    # Adjust plot limits and redraw
                    ax.relim()
                    ax.autoscale_view()
                    plt.draw()
                    plt.pause(0.1)  # Add a short pause to allow the plot to update

            except queue.Empty:
                continue
            except Exception as e:
                self.logger.error(f"Error updating plot: {e}")

        plt.close('all')

    def signal_handler(self, signum, frame):
        self.logger.info("Signal received, shutting down.")
        self.stop_event.set()

    def run(self):
        self.avg_gain = 0.0
        self.avg_loss = 0.0

        signal.signal(signal.SIGINT, lambda signum, frame: self.signal_handler(signum, frame))
        signal.signal(signal.SIGTERM, lambda signum, frame: self.signal_handler(signum, frame))

        plt.ion()
        fig, ax = plt.subplots()
        line, = ax.plot([], [], 'r-', label='RSI')
        ax.axhline(70, color='r', linestyle='--')
        ax.axhline(30, color='g', linestyle='--')
        ax.set_ylim(0, 100)
        ax.set_title(f'RSI for {self.symbol}')
        ax.legend()

        trade_thread = threading.Thread(target=self.start_trade_stream)
        aggregate_thread = threading.Thread(target=self.aggregate_trades_to_candles)

        trade_thread.start()
        aggregate_thread.start()

        self.update_plot(ax, line)  # Run in main thread

        trade_thread.join()
        aggregate_thread.join()

        self.logger.info("Application has shut down cleanly.")

if __name__ == "__main__":
    load_dotenv()
    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_API_SECRET')
    trader = BinanceRSITraderInitial50('BTCUSDT', 14, 50, api_key, api_secret)
    trader.run()

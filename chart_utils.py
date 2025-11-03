import matplotlib.pyplot as plt
from datetime import datetime

def generate_chart(symbol, data):
    """
    Generate a simple price trend chart image.
    `data` is a list of (timestamp, price).
    Returns the image file path.
    """
    times = [datetime.fromisoformat(t) for t, _ in data]
    prices = [p for _, p in data]

    plt.figure(figsize=(6, 3))
    plt.plot(times, prices, color="#FF7F0E", linewidth=2)
    plt.title(f"{symbol} – 24H Price Trend", fontsize=12)
    plt.xlabel("Time")
    plt.ylabel("Price")
    plt.grid(True)
    plt.tight_layout()

    filename = f"{symbol.replace('/', '_')}_chart.png"
    plt.savefig(filename)
    plt.close()
    return filename

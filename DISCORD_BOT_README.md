# Discord Flight Tracker Bot

A Discord bot that allows you to search for flights using Google Flights data through the `fast-flights` library.

## Features

- ✈️ Search for one-way or round-trip flights
- 🔍 Search for airports by name
- 💰 View price status (low/typical/high)
- 📊 See top flight options with details (departure, arrival, duration, stops, price)
- 🎫 Support for different seat classes (economy, premium-economy, business, first)
- 🔄 Filter by maximum number of stops

## Setup

### 1. Create a Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click "New Application" and give it a name
3. Go to the "Bot" section
4. Click "Add Bot" and confirm
5. Under "Token", click "Reset Token" or "Copy" to get your bot token
6. Enable the following Privileged Gateway Intents:
   - Message Content Intent (if you want message commands)
   - Server Members Intent (optional, for member info)

### 2. Invite Bot to Your Server

1. Go to the "OAuth2" → "URL Generator" section
2. Select scopes:
   - `bot`
   - `applications.commands` (for slash commands)
3. Select bot permissions:
   - Send Messages
   - Embed Links
   - Read Message History
4. Copy the generated URL and open it in your browser to invite the bot

### 3. Install Dependencies

```bash
# Using pip
pip install discord.py

# Or using pipenv (if you use Pipfile)
pipenv install discord-py
```

### 4. Configure Bot Token

**Option 1: Environment Variable (Recommended)**

```bash
# Windows (PowerShell)
$env:DISCORD_BOT_TOKEN="your_bot_token_here"

# Windows (CMD)
set DISCORD_BOT_TOKEN=your_bot_token_here

# Linux/Mac
export DISCORD_BOT_TOKEN="your_bot_token_here"
```

**Option 2: Create .env file**

1. Copy `.env.example` to `.env`
2. Add your bot token to the `.env` file
3. Install `python-dotenv`: `pip install python-dotenv`
4. Update `discord_bot.py` to load from `.env`:

```python
from dotenv import load_dotenv
load_dotenv()
```

### 5. Run the Bot

```bash
python discord_bot.py
```

You should see:
```
✅ BotName#1234 is online!
Bot is in X guild(s)
Slash commands synced!
```

## Usage

### Slash Commands

#### `/search_flight`

Search for flights between two airports.

**Parameters:**
- `origin` (required): Origin airport code (e.g., JFK, LAX, TPE)
- `destination` (required): Destination airport code
- `date` (required): Departure date in YYYY-MM-DD format
- `return_date` (optional): Return date for round-trip flights
- `adults` (optional): Number of adult passengers (default: 1)
- `seat_class` (optional): economy, premium-economy, business, or first (default: economy)
- `max_stops` (optional): Maximum number of stops: 0, 1, or 2

**Examples:**

```
/search_flight origin:JFK destination:LAX date:2025-06-15
/search_flight origin:TPE destination:JFK date:2025-07-01 return_date:2025-07-15 adults:2 seat_class:business
/search_flight origin:LAX destination:NYC date:2025-05-20 max_stops:1
```

#### `/search_airport`

Search for airports by name or code.

**Parameters:**
- `query` (required): Airport name or code to search for

**Examples:**

```
/search_airport query:New York
/search_airport query:JFK
/search_airport query:Tokyo
```

#### `/track_flight`

Track flights over a date range and get notified when prices drop below your threshold.

**Parameters:**
- `origin` (required): Origin airport code (e.g., RDU, JFK, LAX)
- `destination` (required): Destination airport code (e.g., MIA, JFK, LAX)
- `max_price` (required): Maximum price threshold in dollars (e.g., 500)
- `start_date` (optional): Start date (YYYY-MM-DD) or `this_month` for all of this month (default: "this_month")
- `days` (optional): Number of days to track from start_date (default: 30, ignored if start_date is "this_month")
- `adults` (optional): Number of adult passengers (default: 1)
- `seat_class` (optional): economy, premium-economy, business, or first (default: economy)
- `max_stops` (optional): Maximum number of stops: 0, 1, or 2

**Examples:**

```
/track_flight origin:RDU destination:MIA max_price:400 start_date:this_month
/track_flight origin:JFK destination:LAX max_price:300 start_date:2025-06-01 days:30
/track_flight origin:TPE destination:NYC max_price:800 seat_class:business
```

**How it works:**
- The bot checks tracked flights every 6 hours
- When a flight price drops below your threshold, you'll get a notification
- The bot samples dates from your range to avoid too many API calls
- Trackers persist until you remove them

#### `/list_trackers`

List all your active flight trackers.

**Example:**
```
/list_trackers
```

#### `/remove_tracker`

Remove a flight tracker by its ID.

**Parameters:**
- `tracker_id` (required): Tracker ID (use `/list_trackers` to find it)

**Example:**
```
/remove_tracker tracker_id:12345678
```

## Example Output

The bot will display flight results in a formatted embed showing:
- Price status (🟢 Low / 🟡 Typical / 🔴 High)
- Trip type
- Top 5 flights with:
  - Airline name
  - Departure and arrival times
  - Duration
  - Number of stops
  - Price
  - Delays (if any)

## Troubleshooting

### Bot doesn't respond to commands

1. Make sure the bot is online (check console output)
2. Wait a few minutes after starting - slash commands may take time to sync
3. Try restarting the bot
4. Check that the bot has the `applications.commands` scope when invited

### "No flights found" error

- Verify airport codes are correct (use `/search_airport` to find codes)
- Check that the date is in the future
- Some routes may not have available flights

### Import errors

Make sure all dependencies are installed:
```bash
pip install discord.py fast-flights
```

## Notes

- The bot uses the `fallback` fetch mode for better reliability
- Flight data is sourced from Google Flights
- Results may take a few seconds to load
- Some routes may require specific fetch modes (common, fallback, local, bright-data)

## License

Same as the main fast-flights project.


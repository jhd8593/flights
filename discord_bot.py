"""
Discord bot for tracking flights using fast-flights
"""
import os
import re
import asyncio
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional, Literal, cast, Dict, List
from collections import defaultdict

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

load_dotenv()

from fast_flights import (
    FlightData,
    Passengers,
    get_flights,
    search_airport,
    Result,
)


@dataclass
class FlightTracker:
    """Stores information about a flight being tracked"""
    user_id: int
    channel_id: int
    origin: str
    destination: str
    start_date: str
    end_date: str
    max_price: float  # Price threshold in dollars
    adults: int
    seat_class: str
    max_stops: Optional[int]
    last_checked: datetime = field(default_factory=datetime.now)
    last_price: Optional[float] = None
    tracker_id: str = field(default_factory=lambda: str(datetime.now().timestamp()))


class FlightBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        # Store active trackers: {tracker_id: FlightTracker}
        self.trackers: Dict[str, FlightTracker] = {}
        # Store trackers by user: {user_id: [tracker_ids]}
        self.user_trackers: Dict[int, List[str]] = defaultdict(list)

    async def setup_hook(self):
        """Sync slash commands when bot starts"""
        await self.tree.sync()
        print("Slash commands synced!")
        # Start the background task
        check_tracked_flights.start()


bot = FlightBot()


async def safe_defer(interaction: discord.Interaction) -> bool:
    if interaction.response.is_done():
        return True
    try:
        await interaction.response.defer(thinking=True)
        return True
    except discord.errors.NotFound:
        return False


def format_price_status(status: str) -> str:
    """Format price status text"""
    status_map = {
        "low": "Low",
        "typical": "Typical",
        "high": "High",
    }
    if not status:
        return "Unknown"
    return status_map.get(status, str(status).replace("-", " ").title())


def format_stops(stops) -> str:
    """Format stops information"""
    if stops == 0:
        return "Nonstop"
    if stops is None:
        return "Stops unknown"
    if isinstance(stops, int):
        return f"{stops} stop" + ("s" if stops != 1 else "")
    return str(stops)


def parse_price(price_str: str) -> Optional[float]:
    """Parse price string to float (handles formats like '$500', '500', '$1,234')"""
    if not price_str:
        return None
    # Remove currency symbols and commas, extract numbers
    price_clean = re.sub(r'[^\d.]', '', price_str.replace(',', ''))
    try:
        return float(price_clean)
    except ValueError:
        return None


def get_dates_in_range(start_date: str, end_date: str) -> List[str]:
    """Get all dates in range (YYYY-MM-DD format)"""
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    dates = []
    current = start
    while current <= end:
        dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return dates


def create_flight_embed(result: Result, origin: str, destination: str, date: str, trip_type: str) -> discord.Embed:
    """Create a Discord embed for flight results"""
    embed = discord.Embed(
        title="Flight Search Results",
        description=f"**{origin.upper()}** -> **{destination.upper()}**\nDate: {date}",
        color=discord.Color.blue(),
        timestamp=datetime.now(),
    )

    # Add price status
    price_status = format_price_status(result.current_price)
    embed.add_field(
        name="Price Status",
        value=price_status,
        inline=True,
    )

    # Add trip type
    embed.add_field(
        name="Trip Type",
        value=trip_type.replace("-", " ").title(),
        inline=True,
    )

    # Show top 5 flights (or fewer if less available)
    flights_to_show = result.flights[:5]
    embed.add_field(
        name=f"Top {len(flights_to_show)} Flights",
        value="\u200b",  # Zero-width space for spacing
        inline=False,
    )

    for i, flight in enumerate(flights_to_show, 1):
        # Format flight info
        best_badge = " [BEST]" if flight.is_best else ""
        delay_info = f" | Delay: {flight.delay}" if flight.delay else ""
        arrival_ahead = f" {flight.arrival_time_ahead}" if flight.arrival_time_ahead else ""

        flight_info = (
            f"**{flight.name}**{best_badge}\n"
            f"Depart: {flight.departure} -> Arrive: {flight.arrival}{arrival_ahead}\n"
            f"Duration: {flight.duration} | {format_stops(flight.stops)}\n"
            f"Price: **{flight.price}**{delay_info}"
        )

        embed.add_field(
            name=f"Flight {i}",
            value=flight_info,
            inline=False,
        )

    embed.set_footer(text="Powered by fast-flights | Google Flights")
    return embed


@bot.tree.command(name="search_flight", description="Search for flights between two airports")
@app_commands.describe(
    origin="Origin airport code (e.g., JFK, LAX, TPE)",
    destination="Destination airport code (e.g., JFK, LAX, TPE)",
    date="Departure date (YYYY-MM-DD)",
    return_date="Return date for round-trip (YYYY-MM-DD, optional)",
    adults="Number of adult passengers (default: 1)",
    seat_class="Seat class: economy, premium-economy, business, or first (default: economy)",
    max_stops="Maximum number of stops: 0, 1, or 2 (optional)",
)
async def search_flight(
    interaction: discord.Interaction,
    origin: str,
    destination: str,
    date: str,
    return_date: Optional[str] = None,
    adults: int = 1,
    seat_class: str = "economy",
    max_stops: Optional[int] = None,
):
    """Search for flights using slash command"""
    if not await safe_defer(interaction):
        return

    try:
        # Validate date format
        datetime.strptime(date, "%Y-%m-%d")
        if return_date:
            datetime.strptime(return_date, "%Y-%m-%d")
    except ValueError:
        await interaction.followup.send(
            "Error: Invalid date format. Please use YYYY-MM-DD (e.g., 2025-01-15)."
        )
        return

    # Validate seat class
    valid_seat_classes: list[Literal["economy", "premium-economy", "business", "first"]] = [
        "economy", "premium-economy", "business", "first"
    ]
    if seat_class not in valid_seat_classes:
        await interaction.followup.send(
            f"Error: Invalid seat class. Must be one of: {', '.join(valid_seat_classes)}."
        )
        return
    
    # Cast to proper literal type
    seat_class_literal: Literal["economy", "premium-economy", "business", "first"] = cast(
        Literal["economy", "premium-economy", "business", "first"], seat_class
    )

    # Validate max_stops
    if max_stops is not None and max_stops not in [0, 1, 2]:
        await interaction.followup.send("Error: max_stops must be 0, 1, or 2.")
        return

    # Determine trip type
    if return_date:
        trip_type: Literal["round-trip", "one-way", "multi-city"] = "round-trip"
        flight_data = [
            FlightData(date=date, from_airport=origin.upper(), to_airport=destination.upper()),
            FlightData(date=return_date, from_airport=destination.upper(), to_airport=origin.upper()),
        ]
    else:
        trip_type = "one-way"
        flight_data = [
            FlightData(date=date, from_airport=origin.upper(), to_airport=destination.upper())
        ]

    try:
        # Search for flights (using html data_source to get Result type)
        result = await asyncio.to_thread(
            get_flights,
            flight_data=flight_data,
            trip=trip_type,
            seat=seat_class_literal,
            passengers=Passengers(adults=adults, children=0, infants_in_seat=0, infants_on_lap=0),
            fetch_mode="fallback",  # Use fallback mode for better reliability
            max_stops=max_stops,
            data_source="html",  # Use html to get Result type instead of DecodedResult
        )

        # Type check - ensure we have a Result object
        if result is None:
            await interaction.followup.send(
                f"No flights found for {origin.upper()} -> {destination.upper()} on {date}."
            )
            return
        
        # Type narrowing - data_source="html" should return Result, but check anyway
        if not isinstance(result, Result):
            await interaction.followup.send(
                "Error: Unexpected result type. Please try again."
            )
            return

        if not result.flights:
            await interaction.followup.send(
                f"No flights found for {origin.upper()} -> {destination.upper()} on {date}."
            )
            return

        # Create and send embed (result is now narrowed to Result type)
        embed = create_flight_embed(result, origin, destination, date, trip_type)
        if return_date:
            embed.description = f"**{origin.upper()}** <-> **{destination.upper()}**\nOutbound: {date} | Return: {return_date}"

        await interaction.followup.send(embed=embed)

    except Exception as e:
        await interaction.followup.send(
            f"Error searching for flights: {str(e)}\n"
            f"Please check your airport codes and try again."
        )


@bot.tree.command(name="search_airport", description="Search for airports by name")
@app_commands.describe(query="Airport name or code to search for")
async def search_airport_cmd(interaction: discord.Interaction, query: str):
    """Search for airports"""
    if not await safe_defer(interaction):
        return

    try:
        airports = await asyncio.to_thread(search_airport, query)
        
        if not airports:
            await interaction.followup.send(f"No airports found matching '{query}'.")
            return

        # Format airport list
        airport_list = []
        for airport in airports[:10]:  # Limit to 10 results
            airport_name = airport.name.replace("_", " ").title()
            airport_list.append(f"`{airport.value}` - {airport_name}")  # type: ignore

        embed = discord.Embed(
            title=f"Airport Search Results for '{query}'",
            description="\n".join(airport_list),
            color=discord.Color.green(),
        )
        
        if len(airports) > 10:
            embed.set_footer(text=f"Showing 10 of {len(airports)} results")

        await interaction.followup.send(embed=embed)

    except Exception as e:
        await interaction.followup.send(f"Error searching airports: {str(e)}")


@bot.tree.command(name="track_flight", description="Track flights and get notified when prices drop below threshold")
@app_commands.describe(
    origin="Origin airport code (e.g., RDU, JFK, LAX)",
    destination="Destination airport code (e.g., MIA, JFK, LAX)",
    start_date="Start date for tracking (YYYY-MM-DD) or 'this_month' for all of this month",
    days="Number of days to track from start_date (default: 30, ignored if start_date is 'this_month')",
    max_price="Maximum price threshold in dollars (e.g., 500)",
    adults="Number of adult passengers (default: 1)",
    seat_class="Seat class: economy, premium-economy, business, or first (default: economy)",
    max_stops="Maximum number of stops: 0, 1, or 2 (optional)",
)
async def track_flight(
    interaction: discord.Interaction,
    origin: str,
    destination: str,
    max_price: float,
    start_date: str = "this_month",
    days: int = 30,
    adults: int = 1,
    seat_class: str = "economy",
    max_stops: Optional[int] = None,
):
    """Set up flight tracking with price alerts"""
    if not await safe_defer(interaction):
        return

    # Validate seat class
    valid_seat_classes: list[Literal["economy", "premium-economy", "business", "first"]] = [
        "economy", "premium-economy", "business", "first"
    ]
    if seat_class not in valid_seat_classes:
        await interaction.followup.send(
            f"Error: Invalid seat class. Must be one of: {', '.join(valid_seat_classes)}."
        )
        return
    
    seat_class_literal: Literal["economy", "premium-economy", "business", "first"] = cast(
        Literal["economy", "premium-economy", "business", "first"], seat_class
    )

    # Validate max_stops
    if max_stops is not None and max_stops not in [0, 1, 2]:
        await interaction.followup.send("Error: max_stops must be 0, 1, or 2.")
        return

    # Calculate date range
    if start_date.lower() == "this_month":
        today = datetime.now()
        start = today.replace(day=1)
        # Get last day of month
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            end = start.replace(month=start.month + 1, day=1) - timedelta(days=1)
        start_date_str = start.strftime("%Y-%m-%d")
        end_date_str = end.strftime("%Y-%m-%d")
    else:
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = start_dt + timedelta(days=days - 1)
            start_date_str = start_date
            end_date_str = end_dt.strftime("%Y-%m-%d")
        except ValueError:
            await interaction.followup.send(
                "Error: Invalid date format. Use YYYY-MM-DD or 'this_month'."
            )
            return

    # Create tracker
    tracker = FlightTracker(
        user_id=interaction.user.id,
        channel_id=interaction.channel.id if interaction.channel else 0,
        origin=origin.upper(),
        destination=destination.upper(),
        start_date=start_date_str,
        end_date=end_date_str,
        max_price=max_price,
        adults=adults,
        seat_class=seat_class,
        max_stops=max_stops,
    )

    # Store tracker
    bot.trackers[tracker.tracker_id] = tracker
    bot.user_trackers[interaction.user.id].append(tracker.tracker_id)

    embed = discord.Embed(
        title="Flight Tracking Started",
        description=f"Tracking flights from **{origin.upper()}** to **{destination.upper()}**",
        color=discord.Color.green(),
    )
    embed.add_field(name="Date Range", value=f"{start_date_str} to {end_date_str}", inline=False)
    embed.add_field(name="Price Alert", value=f"Notify when price <= ${max_price:.2f}", inline=True)
    embed.add_field(name="Passengers", value=f"{adults} adult(s)", inline=True)
    embed.add_field(name="Seat Class", value=seat_class.replace("-", " ").title(), inline=True)
    if max_stops is not None:
        embed.add_field(name="Max Stops", value=str(max_stops), inline=True)
    embed.add_field(name="Tracker ID", value=tracker.tracker_id[:8], inline=False)
    embed.set_footer(text="You'll be notified when prices drop below your threshold!")

    await interaction.followup.send(embed=embed)


@bot.tree.command(name="list_trackers", description="List all your active flight trackers")
async def list_trackers(interaction: discord.Interaction):
    """List all active trackers for the user"""
    if not await safe_defer(interaction):
        return

    user_tracker_ids = bot.user_trackers.get(interaction.user.id, [])
    
    if not user_tracker_ids:
        await interaction.followup.send("No active flight trackers found.")
        return

    trackers = [bot.trackers[tid] for tid in user_tracker_ids if tid in bot.trackers]
    
    if not trackers:
        await interaction.followup.send("No active trackers found.")
        return

    embed = discord.Embed(
        title=f"Your Active Trackers ({len(trackers)})",
        color=discord.Color.blue(),
    )

    for i, tracker in enumerate(trackers, 1):
        last_price_str = f"${tracker.last_price:.2f}" if tracker.last_price else "Not checked yet"
        tracker_info = (
            f"**Route:** {tracker.origin} -> {tracker.destination}\n"
            f"**Dates:** {tracker.start_date} to {tracker.end_date}\n"
            f"**Alert:** <= ${tracker.max_price:.2f}\n"
            f"**Last Price:** {last_price_str}\n"
            f"**ID:** `{tracker.tracker_id[:8]}`"
        )
        embed.add_field(
            name=f"Tracker {i}",
            value=tracker_info,
            inline=False,
        )

    await interaction.followup.send(embed=embed)


@bot.tree.command(name="remove_tracker", description="Remove a flight tracker")
@app_commands.describe(tracker_id="Tracker ID to remove (use /list_trackers to find it)")
async def remove_tracker(interaction: discord.Interaction, tracker_id: str):
    """Remove a flight tracker"""
    if not await safe_defer(interaction):
        return

    # Find tracker by partial ID
    matching_trackers = [
        (tid, t) for tid, t in bot.trackers.items()
        if tid.startswith(tracker_id) and t.user_id == interaction.user.id
    ]

    if not matching_trackers:
        await interaction.followup.send(
            f"No tracker found with ID '{tracker_id}'. Use /list_trackers to see your trackers."
        )
        return

    if len(matching_trackers) > 1:
        await interaction.followup.send(
            f"Multiple trackers match '{tracker_id}'. Please use a longer ID."
        )
        return

    full_id, tracker = matching_trackers[0]
    
    # Remove from both dicts
    del bot.trackers[full_id]
    if full_id in bot.user_trackers[interaction.user.id]:
        bot.user_trackers[interaction.user.id].remove(full_id)

    embed = discord.Embed(
        title="Tracker Removed",
        description=f"Stopped tracking {tracker.origin} -> {tracker.destination}",
        color=discord.Color.orange(),
    )
    await interaction.followup.send(embed=embed)


@tasks.loop(hours=6)  # Check every 6 hours
async def check_tracked_flights():
    """Background task to check tracked flights and send notifications"""
    if not bot.trackers:
        return

    print(f"Checking {len(bot.trackers)} tracked flights...")

    for tracker_id, tracker in list(bot.trackers.items()):
        try:
            # Get dates to check (sample a few dates from the range)
            dates = get_dates_in_range(tracker.start_date, tracker.end_date)
            # Check up to 5 dates to avoid too many API calls
            dates_to_check = dates[::max(1, len(dates) // 5)][:5]

            best_price = None
            best_date = None
            best_flight = None

            for date in dates_to_check:
                try:
                    result = await asyncio.to_thread(
                        get_flights,
                        flight_data=[
                            FlightData(
                                date=date,
                                from_airport=tracker.origin,
                                to_airport=tracker.destination
                            )
                        ],
                        trip="one-way",
                        seat=cast(Literal["economy", "premium-economy", "business", "first"], tracker.seat_class),
                        passengers=Passengers(
                            adults=tracker.adults,
                            children=0,
                            infants_in_seat=0,
                            infants_on_lap=0
                        ),
                        fetch_mode="fallback",
                        max_stops=tracker.max_stops,
                        data_source="html",
                    )

                    if result and isinstance(result, Result) and result.flights:
                        # Find cheapest flight
                        for flight in result.flights:
                            price = parse_price(flight.price)
                            if price and (best_price is None or price < best_price):
                                best_price = price
                                best_date = date
                                best_flight = flight

                    # Small delay between requests
                    await asyncio.sleep(2)

                except Exception as e:
                    print(f"Error checking {tracker.origin} -> {tracker.destination} on {date}: {e}")
                    continue

            # Update tracker
            tracker.last_checked = datetime.now()
            
            # Check if we should send notification
            if best_price is not None:
                tracker.last_price = best_price
                
                # Send notification if price is below threshold
                if best_price <= tracker.max_price:
                    try:
                        channel = bot.get_channel(tracker.channel_id)
                        if channel:
                            user = bot.get_user(tracker.user_id)
                            mention = user.mention if user else f"<@{tracker.user_id}>"
                            
                            embed = discord.Embed(
                                title="Price Alert",
                                description=f"Flight price dropped below your threshold!",
                                color=discord.Color.green(),
                                timestamp=datetime.now(),
                            )
                            embed.add_field(
                                name="Route",
                                value=f"{tracker.origin} -> {tracker.destination}",
                                inline=False,
                            )
                            embed.add_field(
                                name="Date",
                                value=best_date,
                                inline=True,
                            )
                            embed.add_field(
                                name="Price",
                                value=f"${best_price:.2f}",
                                inline=True,
                            )
                            embed.add_field(
                                name="Your Threshold",
                                value=f"${tracker.max_price:.2f}",
                                inline=True,
                            )
                            
                            if best_flight:
                                embed.add_field(
                                    name="Flight Details",
                                    value=(
                                        f"**{best_flight.name}**\n"
                                        f"Depart: {best_flight.departure} -> Arrive: {best_flight.arrival}\n"
                                        f"Duration: {best_flight.duration} | {format_stops(best_flight.stops)}"
                                    ),
                                    inline=False,
                                )
                            
                            embed.set_footer(text=f"Tracker ID: {tracker_id[:8]}")
                            
                            await channel.send(f"{mention}", embed=embed)
                            print(f"Sent price alert for {tracker.origin} -> {tracker.destination}")
                            
                            # Remove tracker after alert (optional - comment out if you want to keep tracking)
                            # del bot.trackers[tracker_id]
                            # if tracker_id in bot.user_trackers[tracker.user_id]:
                            #     bot.user_trackers[tracker.user_id].remove(tracker_id)
                            
                    except Exception as e:
                        print(f"Error sending notification: {e}")

        except Exception as e:
            print(f"Error processing tracker {tracker_id}: {e}")


@check_tracked_flights.before_loop
async def before_check_tracked_flights():
    """Wait until bot is ready before starting the task"""
    await bot.wait_until_ready()


@bot.event
async def on_ready():
    """Called when bot is ready"""
    print(f"BOT ONLINE: {bot.user}")
    print(f"Bot is in {len(bot.guilds)} guild(s)")
    activity = discord.Activity(
        type=discord.ActivityType.watching,
        name="for flight searches"
    )
    await bot.change_presence(activity=activity)

@bot.event
async def on_command_error(ctx, error):
    """Handle command errors"""
    if isinstance(error, commands.CommandNotFound):
        return
    await ctx.send(f"Error: {str(error)}")


def main():
    """Main function to run the bot"""
    token = os.getenv("DISCORD_BOT_TOKEN")
    
    if not token:
        print("Error: DISCORD_BOT_TOKEN environment variable not set!")
        print("Set it in your environment or .env file.")
        return

    try:
        bot.run(token)
    except discord.LoginFailure:
        print("Error: Invalid bot token. Please check your DISCORD_BOT_TOKEN value.")
    except Exception as e:
        print(f"Error starting bot: {str(e)}")


if __name__ == "__main__":
    main()


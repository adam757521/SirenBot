import asyncio
import os
import random
import time
from datetime import datetime, timedelta
from math import ceil
import aiohttp
import discord
from discord.ext import commands, tasks
import json
import sqlite3
import collections

bot = commands.Bot(command_prefix=commands.when_mentioned_or("?"), intents=discord.Intents.all())
bot.remove_command('help')
last_cities = []

with open('data/cities.json', encoding='utf-8-sig') as file:
    cities_data = json.load(file)


def convert_date(date):
    return time.mktime(datetime.strptime(date, "%Y-%m-%d %H:%M:%S").timetuple())


def find_location_data(location):
    return [x for x in cities_data if x["value"] == location]


async def get_sirens_translated():
    async with aiohttp.ClientSession() as requester:
        resp = await requester.get("https://www.oref.org.il/WarningMessages/History/AlertsHistory.json")

        return [{**x, **find_location_data(x['data'])[0]} for x in await resp.json()]


async def get_current_sirens():
    async with aiohttp.ClientSession() as requester:
        resp = await requester.get("https://www.oref.org.il/WarningMessages/Alert/alerts.json",
                                   headers={"X-Requested-With": "XMLHttpRequest", "Referer": "https://www.oref.org.il/"})

        return await resp.text()


@tasks.loop(seconds=20)
async def change_presence():
    watching_statuses = [f"{len(bot.guilds)} servers! | ?help", f"{len(await get_sirens_translated())} Hamas rockets! | ?help"]

    try:
        await bot.change_presence(activity=discord.Activity(name=random.choice(watching_statuses), type=3))
    except ConnectionResetError:
        pass


@tasks.loop(seconds=2.5)
async def handle_sirens():
    global last_cities

    website_content = await get_current_sirens()
    filtered_cities = []
    if website_content != "":
        cities = json.loads(website_content)["data"]
        filtered_cities = [city for city in cities if city not in last_cities]
        last_cities = cities
    else:
        last_cities = []

    if filtered_cities:
        updated_json = [find_location_data(x)[0] for x in filtered_cities]
        locations = [f"{x['name_en']} ({x['countdown']} seconds)" for x in updated_json]

        for guild in bot.guilds:
            cursor = bot.sqlite.cursor()

            sql = "SELECT siren_channel FROM main WHERE guild_id = ?"
            values = (guild.id,)

            cursor.execute(sql, values)
            value = cursor.fetchone()

            cursor.close()

            if value[0] is None:
                continue

            channel = guild.get_channel(int(value[0]))
            if channel is not None:
                location_string = "\n".join(locations) if guild.id != 769617850511392798 \
                    else "\n".join([x for x in locations if x == "Holon"])

                embed = discord.Embed(
                    title="Siren Alert!",
                    description=f"**Locations:** {location_string}",
                    color=0xff0000
                )

                message = await channel.send(embed=embed)

                await message.add_reaction('🟥')


def get_token():
    with open('config.json') as file:
        return json.load(file)["TOKEN"]


def setup(guild_id):
    cursor = bot.sqlite.cursor()

    sql = "SELECT guild_id FROM main WHERE guild_id = ?"
    values = (guild_id,)

    cursor.execute(sql, values)
    value = cursor.fetchone()

    if value is None:
        sql = "INSERT INTO main (guild_id, siren_channel) VALUES (?, ?)"
        values = (guild_id, None)

        cursor.execute(sql, values)
        bot.sqlite.commit()

    cursor.close()


@bot.event
async def on_ready():
    print("----------------------------")
    print("Bot is running on account:")
    print(bot.user)
    print("----------------------------")

    bot.uptime = time.time()
    bot.sqlite = sqlite3.connect("data/database.db")

    handle_sirens.start()
    change_presence.start()


@bot.event
async def on_command_error(ctx, error):
    """
    Error handling.
    :param ctx:
    :param error:
    :return:
    """

    if isinstance(error, commands.CommandNotFound):
        pass  # we don't need to deal with this, useless message & bad practice.

    elif isinstance(error, commands.CommandOnCooldown):
        time_to_wait = timedelta(seconds=round(error.retry_after))
        await ctx.send(embed=discord.Embed(title="Error", description=f"You have to wait {time_to_wait} "
                                                                      f"to use this command again.",
                                           color=0xff0000))

    elif isinstance(error, commands.NoPrivateMessage):
        try:
            await ctx.send(embed=discord.Embed(title="Error",
                                               description="This command may only be executed in a guild.",
                                               color=0xff0000))
        except discord.HTTPException:
            pass

    elif isinstance(error, commands.PrivateMessageOnly):
        await ctx.send(embed=discord.Embed(title="Error",
                                           description="This command may only be executed in a DM.",
                                           color=0xff0000))

    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(embed=discord.Embed(title="Error", description=f"Please pass all the required arguments! "
                                                                      f"Correct format : `{ctx.command.usage}`",
                                           color=0xff0000))
        if ctx.command.is_on_cooldown(ctx):
            ctx.command.reset_cooldown(ctx)

    elif isinstance(error, commands.BadArgument):
        try:
            await ctx.send(embed=discord.Embed(title="Error",
                                               description=str(error),
                                               color=0xff0000))
            if ctx.command.is_on_cooldown(ctx):
                ctx.command.reset_cooldown(ctx)
        except discord.HTTPException:
            pass  # same thing here

    elif isinstance(error, commands.NSFWChannelRequired):
        await ctx.send(embed=discord.Embed(title="Error",
                                           description="This channel is SFW. (Safe For Work)",
                                           color=0xff0000))

    elif isinstance(error, commands.MissingPermissions):
        await ctx.send(embed=discord.Embed(title="Permission Error.",
                                           description="You don't have permission to use this command.",
                                           color=0xff0000))

    elif isinstance(error, commands.CommandInvokeError):
        if "Missing Permissions" in str(error):
            await ctx.send(embed=discord.Embed(title="Permission Error.",
                                               description="I am missing permissions.", color=0xff0000))
        else:
            await ctx.send(embed=discord.Embed(title="Error",
                                               description="An error occurred while executing this command",
                                               color=0xff0000))
            raise error

    else:
        if 'The check functions' not in str(error):
            print("an unknown error has occurred: ")
            raise error


@bot.event
async def on_guild_join(guild):
    setup(guild.id)

    for channel in guild.text_channels:
        if channel.permissions_for(guild.me).send_messages:
            embed = discord.Embed(
                title="Thank you for adding me!",
                description=f"My prefix is '?'\n"
                            f"To see the list of all features and commands, use ?help")

            embed.set_thumbnail(url=bot.user.avatar_url)

            await channel.send(embed=embed)
        break


@bot.event
async def on_message(message):
    if message.guild:
        setup(message.guild.id)

    await bot.process_commands(message)


@bot.command()
async def info(ctx):
    embed = discord.Embed(
        title="Status | SirenBot",
        description="Shows information about SirenBot and siren activity.",
        color=0xff0000
    )

    siren_json = await get_sirens_translated()

    most_siren_city = collections.Counter([x["name_en"] for x in siren_json]).most_common()[0]
    last_siren_city_most = [x for x in siren_json if x["name_en"] == most_siren_city[0]][0]

    uptime = datetime.fromtimestamp(bot.uptime).strftime("%Y-%m-%d, %H:%M:%S")

    embed.add_field(
        name="⏲️ SirenBot Uptime",
        value=f"**SirenBot Has Been Up Since:** {uptime}",
        inline=False
    )

    embed.add_field(
        name="🚨 Last Siren",
        value=f"**Date:** {siren_json[0]['alertDate']}, **Location:** {siren_json[0]['name_en']}",
        inline=False
    )

    embed.add_field(
        name="📜 City With The Most Sirens (last 24 hours)",
        value=f"**Location:** {last_siren_city_most['name_en']}, "
              f"**Last Siren:** {last_siren_city_most['alertDate']}, **Number of Sirens:** {most_siren_city[1]}",
        inline=False
    )

    embed.add_field(
        name="🚀 Number of Sirens (last 24 hours)",
        value=len(siren_json),
        inline=False
    )

    await ctx.send(embed=embed)


@bot.command()
async def help(ctx):
    embed = discord.Embed(
        title="List of commands | SirenBot",
        description="List of usable commands.",
        color=0xff0000
    )

    embed.set_thumbnail(url=bot.user.avatar_url)
    embed.add_field(name="ℹ️ ?help",
                    value="Shows a list of usable commands.",
                    inline=False)

    embed.add_field(name="🚨 ?setsiren [channel]",
                    value="Assigns the siren log to the specified channel.",
                    inline=False)

    embed.add_field(name="🧪 ?testsiren",
                    value="Sends a test siren alert to the siren log assigned channel.",
                    inline=False)

    embed.add_field(name="📜 ?history [city]",
                    value="Shows a 24 hour siren history of the specified city.",
                    inline=False)

    embed.add_field(name="⚙️ ?settings",
                    value="Shows a list of the current server's settings.",
                    inline=False)

    embed.add_field(name="ℹ️ ?info",
                    value="Shows information about SirenBot and siren activity.",
                    inline=False)
    # add cities certain alert

    await ctx.send(embed=embed)


@bot.command()
@commands.guild_only()
@commands.has_permissions(administrator=True)
async def setsiren(ctx, channel: discord.TextChannel = None):
    channel = channel if channel is not None else ctx.channel

    cursor = bot.sqlite.cursor()

    sql = "UPDATE main SET siren_channel = ? WHERE guild_id = ?"
    values = (channel.id, ctx.guild.id)

    cursor.execute(sql, values)
    cursor.close()
    bot.sqlite.commit()

    embed = discord.Embed(
        title="Success!",
        description=f"Set siren alert channel to {channel.mention}.",
        color=0x00ff00
    )

    await ctx.send(embed=embed)


@bot.command()
@commands.guild_only()
async def settings(ctx):
    cursor = bot.sqlite.cursor()

    sql = "SELECT siren_channel FROM main WHERE guild_id = ?"
    values = (ctx.guild.id,)

    cursor.execute(sql, values)
    value = cursor.fetchone()[0]

    cursor.close()

    embed = discord.Embed(
        title=f"{ctx.guild.name}'s Settings",
        description="List of the current server's settings.",
        color=0xff0000
    )

    embed.add_field(name="🚨 Siren Channel", value=f"<#{value}>" if value is not None else value)

    await ctx.send(embed=embed)


@bot.command()
@commands.guild_only()
@commands.has_permissions(administrator=True)
async def testsiren(ctx):
    embed = discord.Embed(
        title="Test Siren!",
        description=f"This is a test siren alert called by {ctx.author.mention}.",
        color=0xff0000
    )

    cursor = bot.sqlite.cursor()

    sql = "SELECT siren_channel FROM main WHERE guild_id = ?"
    values = (ctx.guild.id,)

    cursor.execute(sql, values)
    value = cursor.fetchone()

    cursor.close()

    if value[0] is None:
        raise commands.BadArgument("You have not assigned the siren log to a channel! "
                                   "assign it to a channel using the ?setsiren command.")

    channel = ctx.guild.get_channel(int(value[0]))
    if channel is not None:
        message = await channel.send(embed=embed)

        await message.add_reaction('🟥')
    else:
        raise commands.BadArgument("The siren log assigned channel is not found.")


@bot.command()
async def updateandrestart(ctx):
    if ctx.author.id == 720149174468870205:
        await ctx.send("Bot updating...")
        os.system('git pull origin main')
        await ctx.send("Bot restarting...")

        await bot.change_presence(status=discord.Status.offline)
        await bot.close()


@bot.command()
@commands.guild_only()
async def history(ctx, *, city=None):
    updated_json = [x for x in await get_sirens_translated() if city.lower() in x["name_en"].lower()] if city is not None else await get_sirens_translated()

    if not updated_json:
        description = f"There were no sirens in **{city.title()}** in the last 24 hours." if city is not None \
            else f"There were no sirens in the last 24 hours."
        embed = discord.Embed(
            title="Error",
            description=description,
            color=0xff0000
        )

        await ctx.send(embed=embed)
    else:
        num_of_embeds = ceil((len(updated_json) + 1) / 25)

        title = f"{city.title()}'s History (last 24 hours)." if city is not None else "Siren History (last 24 hours)."
        description = f"There were **{len(updated_json)}** sirens in **{city.title()}** in the last 24 hours." if city is not None else f"There were **{len(updated_json)}** sirens in the last 24 hours."

        embeds = [
            discord.Embed(
                title=f"{title} (Page 1/{num_of_embeds})",
                description=description,
                color=0xff0000
            )
        ]

        for i in range(2, num_of_embeds + 1):
            embeds.append(discord.Embed(
                title=f"{title} (Page {i}/{num_of_embeds})",
                color=0xff0000
            ))

        embed_index = 0
        for index, siren in enumerate(updated_json):
            embeds[embed_index].add_field(name=f"**{index + 1}.**",
                                          value=f"Date: {siren['alertDate']}, Location: {siren['name_en']}",
                                          inline=False)

            if (index + 1) % 25 == 0:
                embed_index += 1

        message = await ctx.send(embed=embeds[0])
        emojis = ["⏪", "◀️", "▶️", "⏩"]

        for emoji in emojis:
            await message.add_reaction(emoji)

        user_page = 0
        while True:
            try:
                reaction, user = await bot.wait_for('reaction_add',
                                                    check=lambda x, y: x.message == message and y == ctx.author,
                                                    timeout=60)
            except asyncio.TimeoutError:
                break

            if reaction.emoji == emojis[0]:
                user_page = 0

            elif reaction.emoji == emojis[1]:
                if user_page > 0:
                    user_page -= 1

            elif reaction.emoji == emojis[2]:
                if user_page < num_of_embeds - 1:
                    user_page += 1

            elif reaction.emoji == emojis[3]:
                user_page = num_of_embeds - 1

            await message.remove_reaction(reaction.emoji, ctx.author)
            await message.edit(embed=embeds[user_page])


if __name__ == "__main__":
    bot.run(get_token())
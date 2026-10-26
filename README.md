# Dolphin City Builder

A text-based, real-time city builder that several people play together in a
browser. It is plain Python (standard library only) plus one HTML page.

| File | What it is |
|---|---|
| `game.py` | All the rules and content: terrain, buildings, research, additions, wildlife, exploring, power. New content is normally one entry in a table at the top. |
| `market.py` | Trades, beast trades and bills between cities. |
| `discord_bot.py` | The game on Discord: slash commands answered by the game server, and announcements. |
| `ideology.py` | Ideologies chosen at Village, and the perks each tech level's point buys. |
| `weather.py` | Day and night (from the player's own clock) and each area's weather, changing every meal, what they do to buildings, shelter from them, and forecasts. |
| `beasts.py` | Beasts: eggs, missions, levelling, stats, pictures and the bonuses they give. |
| `server.py` | The web server, sign-in and saving. Run this to host the game from your own computer. |
| `wsgi.py` | Lets a web host (PythonAnywhere) run the same game. |
| `index.html` | The page players see. |
| `start.bat` | Double-click on Windows to start the game on your own network. |
| `deploy/` | Scripts for running the game on your own Linux server (see "Your own server"). |
| `desktop/` | The downloadable desktop app (`DolphinCityBuilder.exe`) and how it is built. |
| `desktop-app/` | The full desktop app: the game in its own Chromium window (Electron), built into an installer. |

Cities are saved in `saves/` and the market in `market.json`. Both are left out
of git on purpose (see `.gitignore`): they hold each city's password hash, and
the live game's saves must not be overwritten when the code is updated.

## The desktop app

`desktop/DolphinCityBuilder.exe` is a small Windows program that opens the
hosted game in a window of its own, with no tabs or address bar. Everyone who
runs it plays in the same world as the website, and nothing else needs
installing: it uses Microsoft Edge (on every Windows 10 and 11 computer) or
Google Chrome behind the scenes, or the default browser if neither is there.
Players stay signed in between runs; the app keeps its own sign-in, separate
from their browser's.

To share it, give people the `.exe` file. The easiest place is a GitHub
release: on the repository's page choose **Releases**, **Create a new
release**, attach `DolphinCityBuilder.exe`, and publish. Because the program is
not signed, Windows may say it "protected your PC" the first time; choose
**More info** and **Run anyway**.

To rebuild it after changing `desktop/Launcher.cs` (for example if the game
moves to a new address), double-click `desktop/build.bat`. It uses the C#
compiler that comes with Windows. `desktop/make_icon.py` redraws the icon.

## The full desktop app (for an installer, or Steam later)

`desktop-app/` is a more complete version of the desktop app. It brings its
own copy of Chromium (through Electron), so it does not need Edge or Chrome on
the player's computer, and it can be built for Linux too. Like the small
launcher it shows the hosted game, so game updates reach players straight
away and the app itself only needs rebuilding if it changes. It also:

- keeps the player signed in, in storage of its own;
- shows a "Can't reach the game" page that keeps retrying when there is no
  connection or the server is down;
- opens any link away from the game in the player's normal browser;
- allows only one copy to run; F5 reloads and F11 goes full screen.

To build it you need Node.js (from nodejs.org). In a terminal:

```
cd desktop-app
npm install
npm run dist
```

That makes, in `desktop-app/dist/`:

| File | What it is |
|---|---|
| `Dolphin City Builder Setup 1.1.0.exe` | An installer, with Start menu shortcut and uninstaller. |
| `DolphinCityBuilder-1.1.0-portable.exe` | The same app as one file that runs without installing. |
| `win-unpacked/` | The app as a plain folder. This is what Steam would want uploaded. |

They are about 105 MB each, mostly Chromium, so they are not kept in git
(GitHub refuses files over 100 MB). Share them by attaching them to a GitHub
release instead. If `npm run start` says Electron is missing, run
`node node_modules/electron/install.js` once.

`npm run dist:linux` makes a Linux AppImage and folder; it is best run on a
Linux computer. The game's address is at the top of `desktop-app/main.js`, and
raising `version` in `desktop-app/package.json` changes the file names of a
new build. Neither build is code-signed, so Windows shows its "protected your
PC" warning on first run.

## Your own server (for more players, or Steam)

The free PythonAnywhere account is fine for friends, but it is slow under
load and switches off unless renewed every month. For a bigger audience, run
the game on a small Linux server (a "VPS") of your own. The game needs very
little: the cheapest plan of any provider is enough (1 CPU, 1-2 GB of memory),
for example Hetzner (about 4 euros a month) or DigitalOcean (about 6 dollars).

1. **Get a domain name** (about 10 dollars a year from a registrar such as
   Cloudflare or Namecheap), so the game has a permanent address like
   `play.dolphincity.com` and can have HTTPS. Any domain you already own works
   too: a subdomain of it is enough.
2. **Rent the server**: choose Ubuntu 24.04, the smallest size, and add your
   SSH key or a root password when asked. Note its IP address.
3. **Point the domain at the server**: at your registrar, add an "A" record
   for the name you chose (for example `play`) with the server's IP address.
4. **Install the game**: connect with `ssh root@your-server-ip` and run:

   ```
   curl -fsSL https://raw.githubusercontent.com/EthanDolphinP/DolphinCityBuilder/main/deploy/setup.sh -o setup.sh
   bash setup.sh play.yourdomain.com
   ```

   This needs the repository to be public. It installs everything, starts the
   game as a service that restarts by itself and saves on shutdown, gets an
   HTTPS certificate, turns on a firewall, and backs the game up every night.
5. **Bring the cities across** from PythonAnywhere: in a PythonAnywhere Bash
   console run `cd ~/DolphinCityBuilder && tar -czf cities.tar.gz --ignore-failed-read saves market.json discord.json blocked_words.json removed`
   (the cities, the market, the Discord bot's keys, the blocked words and removed cities),
   download `cities.tar.gz` from the Files tab, copy it to the server
   (`scp cities.tar.gz root@your-server-ip:`), and there run
   `dolphincity restore cities.tar.gz`. Do this last thing before telling
   players about the move, so nothing played on PythonAnywhere afterwards is
   lost.
6. **Point Discord at the new address**: in the Discord Developer Portal, under your
   application's General Information, change the Interactions Endpoint URL to
   `https://play.yourdomain.com/api/discord`, then run `dolphincity discord register`.
7. **Point the apps at the new address**: change the address at the top of
   `desktop-app/main.js` (and `desktop/Launcher.cs`), raise the version in
   `desktop-app/package.json`, and rebuild them. Players of the old app need
   the new one; you could leave a present or a message on PythonAnywhere
   telling them where the game has gone.

Looking after it afterwards, over SSH:

| Command | What it does |
|---|---|
| `dolphincity update` | Gets the latest code from GitHub and restarts (instead of `git pull` and Reload). |
| `dolphincity present City "message" wood=100` | Sends a present, as on PythonAnywhere. |
| `dolphincity reset-password City` | The next person to sign in to City chooses its password. |
| `dolphincity backup` / `restore file` | A backup now, or put one back. Nightly backups are in `/var/backups/dolphincity` (14 kept). |
| `dolphincity status` / `logs` / `restart` | How the game service is doing. |

How far this goes: the game keeps every city in memory and handles one request
at a time, each taking around 20 ms for a large city. With the page checking
for news every 5 seconds, that is comfortable for a hundred or two players
online at once. Beyond that the game itself needs changes (a database, more
than one process), not just a bigger server.

## Run it on your own computer

### Preview UI changes with the real hosted game

Double-click `preview-ui.bat`, or run `python preview_ui.py`, then open
`http://127.0.0.1:18744`. This serves your local `index.html` and forwards API
requests to `https://mangoclaw119.pythonanywhere.com`. Sign in with your existing
city name and password. Actions affect your real city; no local game saves are
created. The hosted server code is unchanged. Stop the preview with Ctrl+C.

If the port is busy, use `python preview_ui.py --port 18745` and open the printed
address. The preview needs no extra Python packages. Signing in here does not
reuse your hosted site's browser session, because each address has separate
browser storage.

### Run a separate local game

```
python server.py
```

It prints the address to open. Other devices on the same network can use the
"local network" address.

## Put it on PythonAnywhere (free account)

Replace `YOURNAME` with your PythonAnywhere username everywhere below.

1. **Get the code.** On PythonAnywhere open **Consoles**, start a **Bash**
   console and run:

   ```
   git clone https://github.com/EthanDolphinP/DolphinCityBuilder.git
   ```

   If the repository is private, GitHub will ask for a username and a personal
   access token. Making the repository public avoids that; no passwords or
   saves are stored in it.

2. **Create the web app.** Open the **Web** tab, press **Add a new web app**,
   press Next, choose **Manual configuration** (not Flask or Django), choose the
   newest Python version offered, and finish.

3. **Point it at the game.** On the Web tab, in the **Code** section, click the
   link next to **WSGI configuration file**. Delete everything in that file and
   put in exactly this, then press **Save**:

   ```python
   import sys
   sys.path.insert(0, "/home/YOURNAME/DolphinCityBuilder")
   from wsgi import application
   ```

4. **Start it.** Back on the Web tab press the green **Reload** button, then
   open `https://YOURNAME.pythonanywhere.com`.

If the page shows an error, the **Error log** link on the Web tab says why.

### Keeping it running

- Free web apps expire after a month. Log in and press **Run until 1 month
  from today** on the Web tab before then.
- **Updating the game** after new code is pushed to GitHub: in a Bash console
  run the two lines below, then press **Reload** on the Web tab. Saves are not
  touched.

  ```
  cd ~/DolphinCityBuilder
  git pull
  ```

### Bringing existing cities across (optional)

On the **Files** tab go to `DolphinCityBuilder`, create a folder called `saves`,
and upload the `.json` files from the `saves` folder on your computer. Upload
`market.json` next to `server.py` if you want open offers and bills too. Press
**Reload** on the Web tab afterwards. Do this before people start playing on
the hosted copy, or their progress there will be replaced.

### Sending presents

You can send any city (or every city) a present from a Bash console. The game
does not need to be stopped or reloaded: the present appears the next time
anyone uses the game, wrapped, with an Open button.

```
cd ~/DolphinCityBuilder
python server.py --present CityName "Thanks for testing!" wood=200 gold=50
python server.py --present all "Sorry about the downtime." food=100 egg=rare
```

The message goes in quotes, then as many `material=amount` gifts as you like:
`food`, `wood`, `stone`, `ore`, `tools`, `gold`, `electronics`, `livestock`,
`knowledge`. `egg=` adds a beast egg: `common`, `uncommon`, `rare`, `epic` or
`legendary`. `people=` adds new arrivals, who move in even if every bed is taken.
Use `all` instead of a city name to send it to everyone.

### Discord

The game can answer slash commands in your Discord server (`/leaderboard`,
`/city`, `/market`, `/online`, `/game`) and post announcements to a channel (a
new city, a city reaching a new tech level, an ideology chosen, and a daily
leaderboard). Nothing extra has to keep running: Discord sends each command to
the game's own address, and the game answers it from the live cities.

1. At https://discord.com/developers/applications press **New Application** and
   name it. On **General Information** copy the **Application ID** and the
   **Public Key**. On **Bot**, press **Reset Token** and copy the token (it is
   only shown once; keep it secret).
2. Invite it: **OAuth2**, **URL Generator**, tick `applications.commands` and
   `bot`, and under Bot Permissions tick **Manage Roles** (for `/claim`); open the
   link at the bottom and pick your server.
3. For announcements, in your Discord server open the channel's settings,
   **Integrations**, **Webhooks**, **New Webhook**, **Copy Webhook URL**.
4. In a Bash console on PythonAnywhere:
   ```
   cd ~/DolphinCityBuilder
   python discord_bot.py setup
   python discord_bot.py register
   ```
   `setup` asks for the values above and the game's address, and keeps them in
   `discord.json` next to the saves (never in the code). `register` tells
   Discord about the slash commands; run it again if they ever change.
5. **Reload** the web app, then back on the application's **General
   Information** page set **Interactions Endpoint URL** to
   `https://mangoclaw119.pythonanywhere.com/api/discord` and save. Discord
   checks the address at once; if it is refused, check the Public Key.
6. `python discord_bot.py test` posts a test message to the announcements
   channel. For a daily leaderboard, add a scheduled task on the **Tasks**
   tab: `cd ~/DolphinCityBuilder && python discord_bot.py daily`.

**After every update of the game**, announce it in the same console:

```
cd ~/DolphinCityBuilder && git pull && python discord_bot.py update "A short note, if you like"
```

It posts the changes since the last announcement (the commit messages), with
your note on top, then press **Reload** as usual. With nothing new and no note
it posts nothing.

**Admin commands**, for you only: `/present to: message: gifts:` (gifts as in
`--present`, e.g. `wood=500 gold=200 egg=rare people=5`; `to` can be `all`),
`/announce message:` (posts to the announcements channel) and
`/resetpassword city:`. Discord hides them from everyone without the
Administrator permission in your server, and the game checks again; to let
someone else use them without making them a server admin, add their Discord
user ID in `python discord_bot.py setup`. Run `python discord_bot.py register`
once more so Discord learns about them.

**More, without anyone looking after it:**

- **Milestones** go to the announcements channel by themselves: the first of
  each wonder built in the game (and every Metropolis or Megacity wonder), every
  fifth ideology quest a city completes, and the first city to earn each rare
  tag (and every epic or legendary one).
- **A weekly recap** is posted every Sunday at 17:00 UTC: new cities, new tech
  levels, and who grew, researched, built and quested most that week. The game
  posts it itself. `python discord_bot.py weekly` posts one at once.
- **Roles that follow the game.** A player who has used `/claim` gets a role for
  their city's tech level (Village ... Megacity) and one for its ideology, and
  they change by themselves when the city does. The roles are made if missing.
  The bot's own role must be above them in the role list. `/syncroles` (admin)
  brings everyone up to date.
- **`/claimtag tag:`** (admin): a game tag, such as `alpha`, that everyone gets
  when they claim their city. `off` stops it.
- **`/suggest` and `/bug`** turn a title and details into a post in a forum
  channel, with who sent it, their city and (for bugs) the game's version.
  Choose the forums once with `/setforum` (admin). The bot needs to see each
  forum and create posts in it.
- **`/profile city:`** shows a city's tags, wonders and standing.

Run `python discord_bot.py register` (on the server: `sudo dolphincity discord
register`) after an update that adds commands.

**"Too Many Requests" (429).** Discord sometimes turns away PythonAnywhere,
whose accounts share one internet address. The bot waits when Discord says how
long and tries again; if Discord is blocking the address for a while it says
so: wait a few minutes, or run the same command on your own computer (run
`python discord_bot.py setup` there once, with just the webhook).

**The Land Owner role.** `/claim city: code:` gives a member the **Land
Owner** role (the bot makes it if there is none). The code is on each city's
**Settings** tab in the game, under Discord, and only that city's player sees
it, so nobody can claim someone else's city. For this the bot needs the
**Manage Roles** permission (in the invite link, or in the server's Roles
settings), and the bot's own role must be **above** Land Owner in the role
list. Discord doesn't tell this kind of bot when someone joins, so point new
members at `/claim` in your welcome channel or in Onboarding. After this
update, run `python discord_bot.py register` once more so Discord learns
about `/claim`.

### A forgotten password

In a Bash console, then Reload the web app; whoever signs in to that city next
chooses its new password:

```
cd ~/DolphinCityBuilder
python server.py --reset-password CityName
```

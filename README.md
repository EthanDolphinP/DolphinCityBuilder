# Dolphin City Builder

A text-based, real-time city builder that several people play together in a
browser. It is plain Python (standard library only) plus one HTML page.

| File | What it is |
|---|---|
| `game.py` | All the rules and content: terrain, buildings, research, additions, wildlife, exploring, power. New content is normally one entry in a table at the top. |
| `market.py` | Trades, beast trades and bills between cities. |
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
| `Dolphin City Builder Setup 1.0.0.exe` | An installer, with Start menu shortcut and uninstaller. |
| `DolphinCityBuilder-1.0.0-portable.exe` | The same app as one file that runs without installing. |
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
   console run `cd ~/DolphinCityBuilder && tar -czf cities.tar.gz saves market.json`,
   download `cities.tar.gz` from the Files tab, copy it to the server
   (`scp cities.tar.gz root@your-server-ip:`), and there run
   `dolphincity restore cities.tar.gz`. Do this last thing before telling
   players about the move, so nothing played on PythonAnywhere afterwards is
   lost.
6. **Point the apps at the new address**: change the address at the top of
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
`legendary`. Use `all` instead of a city name to send it to everyone.

### A forgotten password

In a Bash console, then Reload the web app; whoever signs in to that city next
chooses its new password:

```
cd ~/DolphinCityBuilder
python server.py --reset-password CityName
```

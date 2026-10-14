# Dolphin City Builder

A text-based, real-time city builder that several people play together in a
browser. It is plain Python (standard library only) plus one HTML page.

| File | What it is |
|---|---|
| `game.py` | All the rules and content: terrain, buildings, research, additions, wildlife, exploring, power. New content is normally one entry in a table at the top. |
| `market.py` | Trades, beast trades and bills between cities. |
| `beasts.py` | Beasts: eggs, missions, levelling, stats, pictures and the bonuses they give. |
| `server.py` | The web server, sign-in and saving. Run this to host the game from your own computer. |
| `wsgi.py` | Lets a web host (PythonAnywhere) run the same game. |
| `index.html` | The page players see. |
| `start.bat` | Double-click on Windows to start the game on your own network. |
| `desktop/` | The downloadable desktop app (`DolphinCityBuilder.exe`) and how it is built. |

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

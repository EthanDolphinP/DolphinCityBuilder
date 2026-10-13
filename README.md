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

Cities are saved in `saves/` and the market in `market.json`. Both are left out
of git on purpose (see `.gitignore`): they hold each city's password hash, and
the live game's saves must not be overwritten when the code is updated.

## Run it on your own computer

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

### A forgotten password

In a Bash console, then Reload the web app; whoever signs in to that city next
chooses its new password:

```
cd ~/DolphinCityBuilder
python server.py --reset-password CityName
```

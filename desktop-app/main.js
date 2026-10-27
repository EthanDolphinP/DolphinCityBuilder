// Dolphin City Builder: the packaged desktop app.
//
// The game runs on the server, so this app holds none of it: it is a window
// with its own copy of Chromium (from Electron) that shows the hosted game.
// Every update to the game reaches app players the moment the server has it.
// Unlike desktop/DolphinCityBuilder.exe, it does not need Edge or Chrome on
// the player's computer, so it also runs where those are missing (a Steam
// Deck, for instance, once built for Linux).

const { app, BrowserWindow, Menu, dialog, shell, session } = require('electron');
const { autoUpdater } = require('electron-updater');
const path = require('path');

const GAME_URL = process.env.DCB_URL || 'https://dolphincitybuilder.duckdns.org/';   // DCB_URL: test against another copy
const GAME_ORIGIN = new URL(GAME_URL).origin;
const TITLE = 'Dolphin City Builder';

let win = null;

// One window only: starting the app again brings the open one forward.
if (!app.requestSingleInstanceLock()) app.quit();
app.on('second-instance', () => {
  if (!win) return;
  if (win.isMinimized()) win.restore();
  win.focus();
});

function isGame(url) {
  try { return new URL(url).origin === GAME_ORIGIN; } catch { return false; }
}
function openOutside(url) {     // links away from the game open in the player's own browser
  if (/^https?:\/\//.test(url)) shell.openExternal(url);
}
function showOffline() {
  win.loadFile(path.join(__dirname, 'offline.html'), { query: { url: GAME_URL } });
}

function createWindow() {
  win = new BrowserWindow({
    width: 1280, height: 860, minWidth: 360, minHeight: 480,
    title: TITLE, backgroundColor: '#0f1412', show: false,
    icon: path.join(__dirname, 'build', 'icon.png'),
    webPreferences: {
      partition: 'persist:game',      // its own saved storage, so the player stays signed in
      contextIsolation: true, nodeIntegration: false, sandbox: true,
    },
  });
  Menu.setApplicationMenu(null);
  win.once('ready-to-show', () => win.show());
  win.on('page-title-updated', e => e.preventDefault());     // keep the game's name on the window

  // Stay on the game: anything else opens outside the app.
  win.webContents.on('will-navigate', (e, url) => {
    if (!isGame(url) && !url.startsWith('file:')) { e.preventDefault(); openOutside(url); }
  });
  win.webContents.setWindowOpenHandler(({ url }) => { openOutside(url); return { action: 'deny' }; });

  // No connection, or the server is down: a page that keeps trying instead of a blank window.
  win.webContents.on('did-fail-load', (e, code, desc, url, isMainFrame) => {
    if (isMainFrame && code !== -3) showOffline();        // -3 is a load the app cancelled itself
  });

  // F5 or Ctrl+R reloads, F11 toggles full screen (the menu that normally has them is hidden).
  win.webContents.on('before-input-event', (e, input) => {
    if (input.type !== 'keyDown') return;
    if (input.key === 'F5' || (input.control && input.key.toLowerCase() === 'r')) { win.loadURL(GAME_URL); e.preventDefault(); }
    else if (input.key === 'F11') { win.setFullScreen(!win.isFullScreen()); e.preventDefault(); }
  });

  win.loadURL(GAME_URL);
  win.on('closed', () => { win = null; });
}

// ---- updating the app itself ----
// The game updates on the server; this is for the app around it. New versions are published as a GitHub release
// (the one marked Latest) with latest.yml, the installer and its .blockmap. The installed app downloads a new
// version quietly, then offers to restart into it (or installs it when the app is next closed). The portable app
// can't replace itself, so it says a new version is out and opens the download page.
const RELEASES = 'https://github.com/EthanDolphinP/DolphinCityBuilder/releases/latest';
const UPDATE_EVERY = 6 * 3600 * 1000;      // checked at start, then every 6 hours

function newer(a, b) {       // is version a newer than b ("1.10.0" > "1.9.2")
  const x = a.split('.').map(Number), y = b.split('.').map(Number);
  for (let i = 0; i < 3; i++) if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) > (y[i] || 0);
  return false;
}

function watchForUpdates() {
  if (!app.isPackaged) return;
  if (process.env.PORTABLE_EXECUTABLE_DIR) {          // the portable app: say so, and open the download page
    let told = false;
    const check = async () => {
      if (told) return;
      try {
        const text = await (await fetch(`${RELEASES}/download/latest.yml`)).text();
        const latest = (text.match(/^version:\s*(.+)$/m) || [])[1];
        if (latest && newer(latest.trim(), app.getVersion())) {
          told = true;
          const { response } = await dialog.showMessageBox(win, {
            type: 'info', buttons: ['Download it', 'Later'], defaultId: 0, cancelId: 1, title: TITLE,
            message: `Version ${latest.trim()} of the app is out (you have ${app.getVersion()}).`,
            detail: 'This is the portable app, which cannot update itself. Download the new one and use it instead; your city is kept on the server.' });
          if (response === 0) shell.openExternal(RELEASES);
        }
      } catch (error) { /* offline, or no release yet: try again later */ }
    };
    check();
    setInterval(check, UPDATE_EVERY);
    return;
  }
  let asked = false;
  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = true;            // if "Later": installed when the app is next closed
  autoUpdater.on('error', () => {});                   // offline, or no release yet: try again later
  autoUpdater.on('update-downloaded', async info => {
    if (asked) return;
    asked = true;
    const { response } = await dialog.showMessageBox(win, {
      type: 'info', buttons: ['Restart now', 'Later'], defaultId: 0, cancelId: 1, title: TITLE,
      message: `Version ${info.version} of the app is ready.`,
      detail: 'Restart to use it now, or it will be installed the next time you close the app. Your city is kept on the server.' });
    if (response === 0) setImmediate(() => autoUpdater.quitAndInstall());
  });
  const check = () => autoUpdater.checkForUpdates().catch(() => {});
  check();
  setInterval(check, UPDATE_EVERY);
}

app.whenReady().then(() => {
  // The game asks for nothing (camera, location, notifications...), so nothing is granted.
  session.fromPartition('persist:game').setPermissionRequestHandler((wc, permission, callback) => callback(false));
  createWindow();
  watchForUpdates();
});
app.on('window-all-closed', () => app.quit());

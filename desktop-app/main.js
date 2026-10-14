// Dolphin City Builder: the packaged desktop app.
//
// The game runs on the server, so this app holds none of it: it is a window
// with its own copy of Chromium (from Electron) that shows the hosted game.
// Every update to the game reaches app players the moment the server has it.
// Unlike desktop/DolphinCityBuilder.exe, it does not need Edge or Chrome on
// the player's computer, so it also runs where those are missing (a Steam
// Deck, for instance, once built for Linux).

const { app, BrowserWindow, Menu, shell, session } = require('electron');
const path = require('path');

const GAME_URL = process.env.DCB_URL || 'https://mangoclaw119.pythonanywhere.com/';   // DCB_URL: test against another copy
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

app.whenReady().then(() => {
  // The game asks for nothing (camera, location, notifications...), so nothing is granted.
  session.fromPartition('persist:game').setPermissionRequestHandler((wc, permission, callback) => callback(false));
  createWindow();
});
app.on('window-all-closed', () => app.quit());

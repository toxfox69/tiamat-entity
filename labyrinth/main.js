// LABYRINTH: TIAMAT'S DESCENT — Electron Main Process
// Desktop wrapper for the Three.js dungeon crawler
const { app, BrowserWindow, Menu, globalShortcut, screen, ipcMain } = require('electron');
const path = require('path');
const fs = require('fs');

// Production vs dev mode
const isDev = process.argv.includes('--dev');
const isPackaged = app.isPackaged;

// Steam integration (optional — graceful fallback if greenworks not available)
let steamworks = null;
try {
  // Check for steam_appid.txt first
  const appIdPath = isPackaged
    ? path.join(process.resourcesPath, 'steam_appid.txt')
    : path.join(__dirname, 'steam_appid.txt');
  const appId = fs.readFileSync(appIdPath, 'utf8').trim();

  if (appId && appId !== '480' && appId !== '0') {
    steamworks = require('greenworks');
    if (steamworks.init()) {
      console.log('[STEAM] Initialized — App ID:', appId);
    } else {
      console.warn('[STEAM] init() returned false — running without Steam');
      steamworks = null;
    }
  }
} catch (e) {
  // No Steam — that's fine, game runs standalone
  console.log('[STEAM] Not available — running standalone');
  steamworks = null;
}

// Prevent multiple instances
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
  process.exit(0);
}

let mainWindow = null;
let isFullscreen = true;

function createWindow() {
  const primaryDisplay = screen.getPrimaryDisplay();
  const { width, height } = primaryDisplay.workAreaSize;

  mainWindow = new BrowserWindow({
    width: Math.min(1920, width),
    height: Math.min(1080, height),
    minWidth: 800,
    minHeight: 600,
    fullscreen: isFullscreen,
    fullscreenable: true,
    title: "LABYRINTH: TIAMAT'S DESCENT",
    icon: getIconPath(),
    backgroundColor: '#000000',
    autoHideMenuBar: true,
    show: false, // Show after ready-to-show to prevent flash
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: false,
      webgl: true,
      enableWebSQL: false,
      spellcheck: false,
      // Performance: disable features we don't need
      backgroundThrottling: false,
      offscreen: false,
    },
  });

  // Hide menu bar
  Menu.setApplicationMenu(null);

  // Load the game
  mainWindow.loadFile(path.join(__dirname, 'app', 'index.html'));

  // Show window once content is painted (prevents white flash)
  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
    mainWindow.focus();
  });

  // DevTools in dev mode only
  if (isDev && !isPackaged) {
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  }

  // Handle window close
  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  // Prevent navigation away from game
  mainWindow.webContents.on('will-navigate', (event) => {
    event.preventDefault();
  });

  // Prevent opening new windows
  mainWindow.webContents.setWindowOpenHandler(() => {
    return { action: 'deny' };
  });

  // Register keyboard shortcuts
  registerShortcuts();
}

function getIconPath() {
  // Try platform-specific icons first
  const resourcesDir = isPackaged
    ? path.join(process.resourcesPath)
    : path.join(__dirname, 'build', 'resources');

  if (process.platform === 'win32') {
    const ico = path.join(resourcesDir, 'icon.ico');
    if (fs.existsSync(ico)) return ico;
  }

  const png = path.join(resourcesDir, 'icon.png');
  if (fs.existsSync(png)) return png;

  // Fallback: use sprite-tiamat from game assets
  const sprite = path.join(__dirname, 'app', 'assets', 'sprite-tiamat.png');
  if (fs.existsSync(sprite)) return sprite;

  return undefined;
}

function registerShortcuts() {
  // F11: Toggle fullscreen
  mainWindow.webContents.on('before-input-event', (event, input) => {
    if (input.key === 'F11' && input.type === 'keyDown') {
      isFullscreen = !isFullscreen;
      mainWindow.setFullScreen(isFullscreen);
      event.preventDefault();
    }

    // Alt+Enter: Toggle fullscreen (common game shortcut)
    if (input.key === 'Enter' && input.alt && input.type === 'keyDown') {
      isFullscreen = !isFullscreen;
      mainWindow.setFullScreen(isFullscreen);
      event.preventDefault();
    }

    // F12: DevTools (dev mode only)
    if (input.key === 'F12' && input.type === 'keyDown' && isDev) {
      mainWindow.webContents.toggleDevTools();
      event.preventDefault();
    }

    // Escape: Exit fullscreen (don't quit)
    if (input.key === 'Escape' && input.type === 'keyDown' && isFullscreen) {
      isFullscreen = false;
      mainWindow.setFullScreen(false);
      event.preventDefault();
    }

    // Ctrl+Q / Cmd+Q: Quit
    if (input.key === 'q' && (input.control || input.meta) && input.type === 'keyDown') {
      app.quit();
    }
  });
}

// IPC handlers for save/load to filesystem
ipcMain.on('save-to-file', (event, { key, data }) => {
  try {
    const savePath = path.join(app.getPath('userData'), key + '.json');
    fs.writeFileSync(savePath, JSON.stringify(data), 'utf8');
    console.log('[SAVE] Written to', savePath);
  } catch (e) {
    console.error('[SAVE] File write failed:', e);
  }
});

ipcMain.handle('load-from-file', async (event, key) => {
  try {
    const savePath = path.join(app.getPath('userData'), key + '.json');
    if (fs.existsSync(savePath)) {
      return JSON.parse(fs.readFileSync(savePath, 'utf8'));
    }
  } catch (e) {
    console.error('[LOAD] File read failed:', e);
  }
  return null;
});

// Steam achievement IPC
ipcMain.on('steam-achievement', (event, achievementId) => {
  if (steamworks) {
    try {
      steamworks.activateAchievement(achievementId, () => {
        console.log('[STEAM] Achievement unlocked:', achievementId);
      }, (err) => {
        console.error('[STEAM] Achievement error:', err);
      });
    } catch (e) {
      console.warn('[STEAM] Achievement failed:', e);
    }
  } else {
    console.log('[STEAM] Achievement (local):', achievementId);
  }
});

// Fullscreen toggle IPC
ipcMain.on('toggle-fullscreen', () => {
  if (mainWindow) {
    isFullscreen = !isFullscreen;
    mainWindow.setFullScreen(isFullscreen);
  }
});

// App lifecycle
app.whenReady().then(() => {
  createWindow();

  // macOS: re-create window when dock icon clicked
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

// Quit when all windows closed (except macOS)
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

// Focus existing window if second instance attempted
app.on('second-instance', () => {
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  }
});

// Cleanup on quit
app.on('will-quit', () => {
  globalShortcut.unregisterAll();
  if (steamworks) {
    try { steamworks.shutdown(); } catch (e) { /* ignore */ }
  }
});

// Handle GPU process crashes gracefully
app.on('gpu-process-crashed', (event, killed) => {
  console.error('[GPU] Process crashed (killed:', killed, ')');
  if (mainWindow) {
    mainWindow.reload();
  }
});

// Disable hardware acceleration issues on some Linux distros
app.commandLine.appendSwitch('ignore-gpu-blacklist');
app.commandLine.appendSwitch('enable-gpu-rasterization');
app.commandLine.appendSwitch('enable-zero-copy');

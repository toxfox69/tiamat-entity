// LABYRINTH: TIAMAT'S DESCENT — Electron Preload Script
// Bridge between renderer (game) and main process / Steam API
const { contextBridge, ipcRenderer } = require('electron');

// Expose a minimal API to the game renderer
contextBridge.exposeInMainWorld('labyrinth', {
  // Platform info
  platform: process.platform,
  isElectron: true,
  isPackaged: process.argv.includes('--packaged') || !process.argv.includes('--dev'),

  // Steam integration (if available)
  steam: {
    available: false,  // Set to true when greenworks initializes in main process

    // Achievement stubs — wired up when Steam app ID is live
    unlockAchievement: (name) => {
      ipcRenderer.send('steam-achievement', name);
    },

    // Overlay (shift+tab)
    activateOverlay: (type) => {
      ipcRenderer.send('steam-overlay', type || 'Friends');
    },
  },

  // Fullscreen control
  toggleFullscreen: () => {
    ipcRenderer.send('toggle-fullscreen');
  },

  // Version info
  version: '1.0.0',
  engine: 'Three.js r170',
  title: "LABYRINTH: TIAMAT'S DESCENT",

  // Online status check (for data-driver.js offline detection)
  isOnline: () => {
    return navigator.onLine;
  },

  // Save/load game state to local filesystem (future feature)
  saveState: (key, data) => {
    try {
      localStorage.setItem('labyrinth_' + key, JSON.stringify(data));
      return true;
    } catch (e) {
      return false;
    }
  },

  loadState: (key) => {
    try {
      const data = localStorage.getItem('labyrinth_' + key);
      return data ? JSON.parse(data) : null;
    } catch (e) {
      return null;
    }
  },
});

// Notify game when online/offline status changes
window.addEventListener('online', () => {
  window.dispatchEvent(new CustomEvent('labyrinth-online'));
});

window.addEventListener('offline', () => {
  window.dispatchEvent(new CustomEvent('labyrinth-offline'));
});

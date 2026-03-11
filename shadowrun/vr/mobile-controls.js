/**
 * SHADOWRUN VR — Mobile Device Detection & Touch Controls
 * Detects iOS/Android and adds touch-friendly UI
 */

const MobileControls = (() => {
  const DEVICE = {
    isIOS: /iPad|iPhone|iPod/.test(navigator.userAgent),
    isAndroid: /Android/.test(navigator.userAgent),
    isMobile: /iPad|iPhone|iPod|Android|webOS|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent),
    isTouchDevice: () => {
      return (typeof window !== 'undefined') &&
        (('ontouchstart' in window) ||
         (navigator.maxTouchPoints > 0) ||
         (navigator.msMaxTouchPoints > 0));
    }
  };

  function createTouchControls() {
    const container = document.createElement('div');
    container.id = 'mobile-controls';
    container.style.cssText = `
      position: fixed; bottom: 20px; right: 20px; width: 200px; z-index: 9000;
      font-family: 'Courier New', monospace; color: #0f0; font-size: 11px;
    `;

    // D-Pad / Joystick area
    const dpadDiv = document.createElement('div');
    dpadDiv.style.cssText = `
      background: #000; border: 2px solid #0f0; padding: 10px; margin-bottom: 10px;
      text-align: center; box-shadow: 0 0 10px rgba(0, 255, 0, 0.3);
    `;
    dpadDiv.innerHTML = `
      <div style="margin-bottom: 5px; font-weight: bold; font-size: 10px;">MOVE</div>
      <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 3px;">
        <div></div>
        <button id="btn-up" style="padding: 8px; background: #0f0; color: #000; border: none; cursor: pointer; font-weight: bold;">▲</button>
        <div></div>
        <button id="btn-left" style="padding: 8px; background: #0f0; color: #000; border: none; cursor: pointer; font-weight: bold;">◀</button>
        <button id="btn-select" style="padding: 8px; background: #666; color: #fff; border: none; cursor: pointer; font-size: 9px;">OK</button>
        <button id="btn-right" style="padding: 8px; background: #0f0; color: #000; border: none; cursor: pointer; font-weight: bold;">▶</button>
        <div></div>
        <button id="btn-down" style="padding: 8px; background: #0f0; color: #000; border: none; cursor: pointer; font-weight: bold;">▼</button>
        <div></div>
      </div>
    `;

    // Action buttons
    const actionsDiv = document.createElement('div');
    actionsDiv.style.cssText = `
      background: #000; border: 2px solid #f00; padding: 10px;
      box-shadow: 0 0 10px rgba(255, 0, 0, 0.3);
    `;
    actionsDiv.innerHTML = `
      <div style="margin-bottom: 5px; font-weight: bold; font-size: 10px;">ACTIONS</div>
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 5px;">
        <button id="btn-talk" style="padding: 6px; background: #0f0; color: #000; border: none; cursor: pointer; font-size: 10px; font-weight: bold;">TALK</button>
        <button id="btn-attack" style="padding: 6px; background: #f00; color: #fff; border: none; cursor: pointer; font-size: 10px; font-weight: bold;">ATTACK</button>
        <button id="btn-inv" style="padding: 6px; background: #00f; color: #fff; border: none; cursor: pointer; font-size: 10px; font-weight: bold;">INV</button>
        <button id="btn-menu" style="padding: 6px; background: #666; color: #fff; border: none; cursor: pointer; font-size: 10px; font-weight: bold;">MENU</button>
      </div>
    `;

    container.appendChild(dpadDiv);
    container.appendChild(actionsDiv);
    return container;
  }

  function createDeviceIndicator() {
    const indicator = document.createElement('div');
    indicator.id = 'device-indicator';
    indicator.style.cssText = `
      position: fixed; top: 10px; right: 10px; background: #000; border: 1px solid #0f0;
      padding: 5px 10px; font-family: 'Courier New', monospace; color: #0f0; font-size: 9px;
      z-index: 9999;
    `;

    let deviceText = 'Desktop';
    if (DEVICE.isIOS) deviceText = 'iOS';
    else if (DEVICE.isAndroid) deviceText = 'Android';
    else if (DEVICE.isMobile) deviceText = 'Mobile';

    indicator.textContent = `[${deviceText}] ${DEVICE.isTouchDevice() ? 'Touch' : 'No Touch'}`;
    return indicator;
  }

  function attachEventListeners() {
    const buttons = {
      'btn-up': 'ArrowUp',
      'btn-down': 'ArrowDown',
      'btn-left': 'ArrowLeft',
      'btn-right': 'ArrowRight',
      'btn-select': 'Enter',
      'btn-talk': 'KeyT',
      'btn-attack': 'KeyA',
      'btn-inv': 'KeyI',
      'btn-menu': 'Escape'
    };

    Object.entries(buttons).forEach(([btnId, keyCode]) => {
      const btn = document.getElementById(btnId);
      if (btn) {
        btn.addEventListener('click', () => {
          const event = new KeyboardEvent('keydown', {
            key: keyCode,
            code: keyCode,
            bubbles: true,
            cancelable: true
          });
          document.dispatchEvent(event);
          console.log(`[MOBILE] Simulated: ${keyCode}`);
        });
      }
    });
  }

  function init() {
    console.log(`[MOBILE-CONTROLS] Device: ${DEVICE.isIOS ? 'iOS' : DEVICE.isAndroid ? 'Android' : 'Desktop'}`);

    // Add device indicator
    const indicator = createDeviceIndicator();
    document.body.appendChild(indicator);

    // If mobile device, add touch controls
    if (DEVICE.isMobile && DEVICE.isTouchDevice()) {
      console.log('[MOBILE-CONTROLS] Adding touch UI');
      const touchUI = createTouchControls();
      document.body.appendChild(touchUI);
      attachEventListeners();
      console.log('[MOBILE-CONTROLS] Touch controls initialized');
    } else {
      console.log('[MOBILE-CONTROLS] Desktop detected - no touch UI needed');
    }
  }

  return {
    init: init,
    getDevice: () => DEVICE
  };
})();

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', MobileControls.init);
} else {
  MobileControls.init();
}

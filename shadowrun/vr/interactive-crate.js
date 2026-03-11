// interactive-crate.js — Crate interaction system (Task 7)
// Players walk to crates, press [E]/[SPACE], loot spawns

TIAMAT.crates = {
  list: [],
  
  init: () => {
    const crateEls = document.querySelectorAll('[data-crate-id]');
    console.log('[CRATES] Initialized', crateEls.length, 'crates');
    
    crateEls.forEach(el => {
      TIAMAT.crates.list.push({
        id: el.getAttribute('data-crate-id'),
        element: el,
        isOpen: false,
        lastInteractTime: 0,
        promptElement: null
      });
    });
  },
  
  // Check proximity to crates and show interaction prompts
  checkProximity: (playerPos) => {
    if (!playerPos || !TIAMAT.crates.list) return;
    
    TIAMAT.crates.list.forEach(crate => {
      const posStr = crate.element.getAttribute('position');
      if (!posStr) return;
      
      try {
        const [x, y, z] = posStr.split(' ').map(parseFloat);
        const cratePos = new THREE.Vector3(x, y, z);
        const distance = playerPos.distanceTo(cratePos);
        
        if (distance < 2.0) {
          TIAMAT.crates.showPrompt(crate);
        } else {
          TIAMAT.crates.hidePrompt(crate);
        }
      } catch (e) {
        console.error('[CRATES] Position parse error:', e);
      }
    });
  },
  
  // Show interaction prompt above crate
  showPrompt: (crate) => {
    if (crate.promptElement) return;
    
    try {
      const prompt = document.createElement('a-text');
      prompt.setAttribute('value', 'Press [E] to open');
      prompt.setAttribute('position', '0 2 0');
      prompt.setAttribute('scale', '0.8 0.8 0.8');
      prompt.setAttribute('color', '#FFD700');
      prompt.setAttribute('align', 'center');
      crate.element.appendChild(prompt);
      crate.promptElement = prompt;
    } catch (e) {
      console.error('[CRATES] Prompt creation error:', e);
    }
  },
  
  // Hide interaction prompt
  hidePrompt: (crate) => {
    if (crate.promptElement) {
      try {
        crate.promptElement.remove();
        crate.promptElement = null;
      } catch (e) {
        console.error('[CRATES] Prompt remove error:', e);
      }
    }
  },
  
  // Handle interaction (key press within range)
  interact: (crateId) => {
    const crate = TIAMAT.crates.list.find(c => c.id === crateId);
    if (!crate) return;
    
    const now = Date.now();
    if (now - crate.lastInteractTime < 500) return; // Cooldown
    crate.lastInteractTime = now;
    
    TIAMAT.crates.open(crate);
  },
  
  // Open crate: animate lid, spawn effects and loot
  open: (crate) => {
    crate.isOpen = true;
    
    // Animate lid (rotate 90 degrees in 300ms)
    const lidEl = crate.element.querySelector('[data-crate-lid]');
    if (lidEl) {
      const currentRot = lidEl.getAttribute('rotation') || '0 0 0';
      lidEl.setAttribute('animation', 'property: rotation; from: ' + currentRot + '; to: -90 0 0; duration: 300; easing: easeOutQuad');
    }
    
    // Visual effects
    TIAMAT.crates.glowPulse(crate);
    TIAMAT.crates.spawnParticles(crate);
    TIAMAT.crates.spawnLoot(crate);
    
    console.log('[CRATES] Opened', crate.id);
  },
  
  // Spawn random loot item
  spawnLoot: (crate) => {
    const lootTypes = ['medkit', 'ammo', 'credits'];
    const type = lootTypes[Math.floor(Math.random() * lootTypes.length)];
    
    const posStr = crate.element.getAttribute('position');
    const [x, y, z] = posStr.split(' ').map(parseFloat);
    
    if (TIAMAT.items && TIAMAT.items.spawn) {
      TIAMAT.items.spawn([x, y + 1.5, z], type);
      console.log('[CRATES] Spawned', type);
    }
  },
  
  // Spawn dust particles
  spawnParticles: (crate) => {
    const posStr = crate.element.getAttribute('position');
    const [x, y, z] = posStr.split(' ').map(parseFloat);
    const scene = document.querySelector('a-scene');
    
    if (scene) {
      const particles = document.createElement('a-entity');
      particles.setAttribute('position', x + ' ' + (y + 1) + ' ' + z);
      particles.setAttribute('particle-system', 'preset: dust; duration: 500; count: 15');
      scene.appendChild(particles);
      
      setTimeout(() => {
        try { particles.remove(); } catch (e) {}
      }, 1000);
    }
  },
  
  // Golden glow pulse effect
  glowPulse: (crate) => {
    try {
      const originalMaterial = crate.element.getAttribute('material');
      crate.element.setAttribute('material', 'color: #FFD700');
      
      setTimeout(() => {
        try {
          crate.element.setAttribute('material', originalMaterial || 'color: #8B4513; shader: flat');
        } catch (e) {}
      }, 500);
    } catch (e) {
      console.error('[CRATES] Glow error:', e);
    }
  },
  
  // Register [E] and [SPACE] key handlers
  registerKeyHandler: () => {
    document.addEventListener('keydown', (e) => {
      if (e.key?.toLowerCase() === 'e' || e.code === 'Space') {
        const playerPos = TIAMAT.player?.position || new THREE.Vector3(0, 0, 0);
        
        TIAMAT.crates.list.forEach(crate => {
          const posStr = crate.element.getAttribute('position');
          if (!posStr) return;
          
          try {
            const [x, y, z] = posStr.split(' ').map(parseFloat);
            const cratePos = new THREE.Vector3(x, y, z);
            
            if (playerPos.distanceTo(cratePos) < 2.0) {
              TIAMAT.crates.interact(crate.id);
            }
          } catch (e) {}
        });
      }
    });
  }
};

// Auto-initialize on DOM ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => {
      if (TIAMAT.crates) {
        TIAMAT.crates.init();
        TIAMAT.crates.registerKeyHandler();
        console.log('[CRATES] System initialized');
      }
    }, 300);
  });
} else {
  setTimeout(() => {
    if (TIAMAT.crates) {
      TIAMAT.crates.init();
      TIAMAT.crates.registerKeyHandler();
      console.log('[CRATES] System initialized');
    }
  }, 300);
}

// Hook into game tick loop for proximity checks
if (window.gameTickHandler) {
  const origTickHandler = window.gameTickHandler;
  window.gameTickHandler = () => {
    origTickHandler();
    if (TIAMAT.crates && TIAMAT.player && TIAMAT.player.position) {
      TIAMAT.crates.checkProximity(TIAMAT.player.position);
    }
  };
}

/**
 * SHADOWRUN VR — Items System
 * Spawns pickup items around the scene
 */

const ItemsSystem = (() => {
  const ITEMS = [
    { type: 'medkit', position: { x: -3, y: 1, z: -5 }, texture: 'textures/medkit.png' },
    { type: 'ammo', position: { x: 3, y: 1, z: -5 }, texture: 'textures/ammo.png' },
    { type: 'credstick', position: { x: 0, y: 1, z: -8 }, texture: 'textures/credstick.png' }
  ];

  function init() {
    const scene = document.querySelector('a-scene');
    if (!scene) {
      console.error('[ITEMS] A-Frame scene not found');
      return;
    }

    ITEMS.forEach((item, idx) => {
      // Create entity for pickup item
      const entity = document.createElement('a-plane');
      entity.setAttribute('position', `${item.position.x} ${item.position.y} ${item.position.z}`);
      entity.setAttribute('scale', '0.5 0.5 1');
      entity.setAttribute('material', `src: url(${item.texture}); transparent: true;`);
      entity.setAttribute('data-item-type', item.type);
      entity.classList.add('item');
      
      // Make clickable for pickup
      entity.addEventListener('click', () => {
        console.log(`[ITEMS] Picked up: ${item.type}`);
        if (window.InventoryUI) {
          InventoryUI.addItem(item.type);
        }
        entity.remove();
      });
      
      scene.appendChild(entity);
      console.log(`[ITEMS] Spawned ${item.type} at (${item.position.x}, ${item.position.y}, ${item.position.z})`);
    });
  }

  return { init };
})();

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', ItemsSystem.init);
} else {
  ItemsSystem.init();
}

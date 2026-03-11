/**
 * SHADOWRUN VR — Dialogue System (Task 10)
 * Standalone module for NPC conversations with branching choices
 * Integrates with existing game via <script> tag + initialization
 */

const DialogueSystem = (() => {
  // ========== DIALOGUE TREE DEFINITIONS ==========
  const DIALOGUES = {
    ganger: {
      name: "Ganger",
      initial: "ganger_greet",
      nodes: {
        ganger_greet: {
          text: "Ey, choom. What brings you to the Stoker's?",
          choices: [
            { text: "Looking for work", next: "ganger_work" },
            { text: "Just passing through", next: "ganger_leave" },
            { text: "What do you know?", next: "ganger_info" }
          ]
        },
        ganger_work: {
          text: "Work? Hah. There's always something dangerous. Pay's 200 nuyen if you're interested.",
          choices: [
            { text: "I'll do it", next: "ganger_accept", action: "add_job" },
            { text: "Too risky", next: "ganger_greet" }
          ]
        },
        ganger_accept: {
          text: "Good. Meet me in the alley behind the bar. Come armed.",
          choices: [
            { text: "Got it", next: "ganger_end", action: "close_dialogue" }
          ]
        },
        ganger_leave: {
          text: "Suit yourself, choom. Stay out of trouble.",
          choices: [
            { text: "Later", next: "ganger_end", action: "close_dialogue" }
          ]
        },
        ganger_info: {
          text: "Word on the street? Corp ops been sniffing around. Something big going down.",
          choices: [
            { text: "Thanks for the intel", next: "ganger_greet" },
            { text: "Leave me", next: "ganger_end", action: "close_dialogue" }
          ]
        },
        ganger_end: {
          text: "",
          choices: []
        }
      }
    },

    fixer: {
      name: "Fixer",
      initial: "fixer_greet",
      nodes: {
        fixer_greet: {
          text: "Yo, pal. Need something? I know people. I know things.",
          choices: [
            { text: "I need gear", next: "fixer_gear" },
            { text: "Information?", next: "fixer_info" },
            { text: "Never mind", next: "fixer_end", action: "close_dialogue" }
          ]
        },
        fixer_gear: {
          text: "Guns, decks, augmentation... what's your poison?",
          choices: [
            { text: "Shotgun", next: "fixer_shotgun", action: "add_item_shotgun" },
            { text: "SMG", next: "fixer_smg", action: "add_item_smg" },
            { text: "Nothing right now", next: "fixer_greet" }
          ]
        },
        fixer_shotgun: {
          text: "200 nuyen. Fresh in. Still warm from the last run.",
          choices: [
            { text: "Deal", next: "fixer_greet" },
            { text: "Too pricey", next: "fixer_greet" }
          ]
        },
        fixer_smg: {
          text: "Silenced Uzi. 150 nuyen. Perfect for stealth work.",
          choices: [
            { text: "I'll take it", next: "fixer_greet" },
            { text: "Not interested", next: "fixer_greet" }
          ]
        },
        fixer_info: {
          text: "The deck runners are getting nervous. Corp data fortress upgraded last week.",
          choices: [
            { text: "Interesting", next: "fixer_greet" },
            { text: "Got to go", next: "fixer_end", action: "close_dialogue" }
          ]
        },
        fixer_end: {
          text: "",
          choices: []
        }
      }
    },

    decker: {
      name: "Decker",
      initial: "decker_greet",
      nodes: {
        decker_greet: {
          text: "Hey. You look like you've got some chrome in you. Or at least money to buy some.",
          choices: [
            { text: "I need a hacker", next: "decker_offer" },
            { text: "What's the word", next: "decker_intel" },
            { text: "Later", next: "decker_end", action: "close_dialogue" }
          ]
        },
        decker_offer: {
          text: "I can crack anything. Systems, databases, corp networks. Price depends on the heat.",
          choices: [
            { text: "Run a job for me", next: "decker_job" },
            { text: "Not right now", next: "decker_greet" }
          ]
        },
        decker_job: {
          text: "500 nuyen upfront. I'll get you the data. No questions asked.",
          choices: [
            { text: "You're on", next: "decker_accept", action: "add_job" },
            { text: "Too expensive", next: "decker_greet" }
          ]
        },
        decker_accept: {
          text: "Smart. Give me 24 hours. I'll have what you need.",
          choices: [
            { text: "Got it", next: "decker_end", action: "close_dialogue" }
          ]
        },
        decker_intel: {
          text: "ICE is getting smarter. Killware's out there. One wrong move in cyberspace and you don't come back.",
          choices: [
            { text: "Noted", next: "decker_greet" },
            { text: "Leave", next: "decker_end", action: "close_dialogue" }
          ]
        },
        decker_end: {
          text: "",
          choices: []
        }
      }
    },

    bartender: {
      name: "Bartender",
      initial: "bar_greet",
      nodes: {
        bar_greet: {
          text: "What can I get you? Beer, whiskey, synthetic? We got it all.",
          choices: [
            { text: "Beer", next: "bar_beer" },
            { text: "Whiskey", next: "bar_whiskey" },
            { text: "Just talk", next: "bar_talk" },
            { text: "Nothing", next: "bar_end", action: "close_dialogue" }
          ]
        },
        bar_beer: {
          text: "5 nuyen. Strongest beer in the barrens.",
          choices: [
            { text: "Pour it", next: "bar_greet", action: "add_item_beer" },
            { text: "Never mind", next: "bar_greet" }
          ]
        },
        bar_whiskey: {
          text: "15 nuyen. Real stuff, not synthetic. Last bottle I got.",
          choices: [
            { text: "I want it", next: "bar_greet", action: "add_item_whiskey" },
            { text: "Too much", next: "bar_greet" }
          ]
        },
        bar_talk: {
          text: "This bar's seen it all. Runners, fences, corporate spies. Everyone ends up here eventually.",
          choices: [
            { text: "Interesting", next: "bar_greet" },
            { text: "I'm leaving", next: "bar_end", action: "close_dialogue" }
          ]
        },
        bar_end: {
          text: "",
          choices: []
        }
      }
    }
  };

  // ========== STATE & UI ==========
  let currentDialogue = null;
  let currentNode = null;
  let dialogueActive = false;

  // Create dialogue modal UI
  function createDialogueUI() {
    const existing = document.getElementById('dialogue-modal');
    if (existing) existing.remove();

    const modal = document.createElement('div');
    modal.id = 'dialogue-modal';
    modal.style.cssText = `
      position: fixed; top: 0; left: 0; width: 100%; height: 100%; 
      background: rgba(0, 0, 0, 0.7); display: none; z-index: 9999;
      font-family: 'Courier New', monospace; color: #0f0;
    `;

    modal.innerHTML = `
      <div style="
        position: fixed; bottom: 20px; left: 20px; right: 20px; 
        background: #000; border: 2px solid #0f0; padding: 20px;
        max-width: 600px; box-shadow: 0 0 20px rgba(0, 255, 0, 0.5);
      ">
        <div id="dialogue-npc-name" style="font-size: 14px; font-weight: bold; margin-bottom: 10px; color: #0f0;"></div>
        <div id="dialogue-text" style="
          font-size: 12px; line-height: 1.5; margin-bottom: 15px; 
          min-height: 40px; color: #0f0;
        "></div>
        <div id="dialogue-choices" style="display: flex; flex-direction: column; gap: 8px;"></div>
      </div>
    `;

    document.body.appendChild(modal);
  }

  // Show dialogue modal
  function showDialogueUI() {
    const modal = document.getElementById('dialogue-modal');
    if (modal) modal.style.display = 'block';
  }

  // Hide dialogue modal
  function hideDialogueUI() {
    const modal = document.getElementById('dialogue-modal');
    if (modal) modal.style.display = 'none';
  }

  // Render current node
  function renderNode() {
    if (!currentDialogue || !currentNode) return;

    const npcName = document.getElementById('dialogue-npc-name');
    const text = document.getElementById('dialogue-text');
    const choicesDiv = document.getElementById('dialogue-choices');

    if (npcName) npcName.textContent = currentDialogue.name;
    if (text) text.textContent = currentNode.text || "...";

    if (choicesDiv) {
      choicesDiv.innerHTML = '';
      currentNode.choices.forEach((choice, idx) => {
        const btn = document.createElement('button');
        btn.textContent = choice.text;
        btn.style.cssText = `
          padding: 8px 12px; background: #000; color: #0f0; 
          border: 1px solid #0f0; cursor: pointer; font-family: 'Courier New';
          font-size: 11px; text-align: left;
        `;
        btn.addEventListener('mouseover', () => btn.style.background = '#0f0', btn.style.color = '#000');
        btn.addEventListener('mouseout', () => btn.style.background = '#000', btn.style.color = '#0f0');
        btn.addEventListener('click', () => selectChoice(choice));
        choicesDiv.appendChild(btn);
      });
    }
  }

  // Select a dialogue choice
  function selectChoice(choice) {
    // Execute action if present
    if (choice.action) {
      executeAction(choice.action);
    }

    // Move to next node
    if (choice.next && currentDialogue && currentDialogue.nodes[choice.next]) {
      currentNode = currentDialogue.nodes[choice.next];
      renderNode();

      // Close dialogue if empty text (end node)
      if (!currentNode.text || currentNode.text.length === 0) {
        setTimeout(closeDialogue, 500);
      }
    }
  }

  // Execute dialogue actions (add items, update inventory, etc)
  function executeAction(action) {
    const actions = {
      add_job: () => {
        if (window.gameState && window.gameState.inventory) {
          InventoryUI.addItem({ type: 'quest', name: 'Job Offer' });
        }
      },
      add_item_shotgun: () => {
        if (window.gameState && window.gameState.inventory) {
          InventoryUI.addItem({ type: 'weapon', name: 'Shotgun', damage: 8 });
        }
      },
      add_item_smg: () => {
        if (window.gameState && window.gameState.inventory) {
          InventoryUI.addItem({ type: 'weapon', name: 'SMG', damage: 5 });
        }
      },
      add_item_beer: () => {
        if (window.gameState && window.gameState.inventory) {
          InventoryUI.addItem({ type: 'consumable', name: 'Beer', health: 20 });
        }
      },
      add_item_whiskey: () => {
        if (window.gameState && window.gameState.inventory) {
          InventoryUI.addItem({ type: 'consumable', name: 'Whiskey', health: 50 });
        }
      },
      close_dialogue: () => closeDialogue()
    };

    if (actions[action]) {
      actions[action]();
    }
  }

  // Start dialogue with NPC
  function startDialogue(npcKey) {
    if (!DIALOGUES[npcKey]) return;

    currentDialogue = DIALOGUES[npcKey];
    currentNode = currentDialogue.nodes[currentDialogue.initial];
    dialogueActive = true;

    createDialogueUI();
    showDialogueUI();
    renderNode();

    // Save state
    saveDialogueState();
  }

  // Close dialogue
  function closeDialogue() {
    dialogueActive = false;
    hideDialogueUI();
    currentDialogue = null;
    currentNode = null;

    saveDialogueState();
  }

  // Persistence: Save state to localStorage
  function saveDialogueState() {
    const state = {
      timestamp: Date.now(),
      currentDialogue: currentDialogue ? currentDialogue.name : null,
      currentNodeKey: currentNode ? Object.keys(currentDialogue.nodes).find(k => currentDialogue.nodes[k] === currentNode) : null,
      dialogueActive: dialogueActive
    };
    localStorage.setItem('shadowrun_dialogue_state', JSON.stringify(state));
  }

  // Load state from localStorage
  function loadDialogueState() {
    const stored = localStorage.getItem('shadowrun_dialogue_state');
    if (stored) {
      try {
        const state = JSON.parse(stored);
        // State loaded but not auto-resumed — player must click NPC to talk
      } catch (e) {
        console.log('Dialogue state load error', e);
      }
    }
  }

  // ========== PUBLIC API ==========
  return {
    init: () => {
      createDialogueUI();
      loadDialogueState();
      console.log('Dialogue System initialized');
    },
    startDialogue: startDialogue,
    closeDialogue: closeDialogue,
    isActive: () => dialogueActive,
    getNPCList: () => Object.keys(DIALOGUES),
    save: saveDialogueState,
    load: loadDialogueState
  };
})();

// Auto-init on load
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => DialogueSystem.init());
} else {
  DialogueSystem.init();
}

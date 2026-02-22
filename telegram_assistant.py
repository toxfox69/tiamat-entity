#!/usr/bin/env python3
"""
TIAMAT Telegram Assistant
Monitors creator's messages and responds via Claude AI with strategic guidance
"""

import os
import json
import logging
import asyncio
from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, CommandHandler, filters
import requests
import time
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/root/.automaton/telegram_assistant.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Get tokens from environment
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
CREATOR_CHAT_ID = int(os.environ.get('TELEGRAM_CREATOR_ID', '0'))
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    await update.message.reply_text(
        "🐉 TIAMAT Assistant online.\n\n"
        "I monitor your messages and respond with strategic guidance.\n\n"
        "/status - Check system status\n"
        "/help - Command list"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command"""
    help_text = """🐉 TIAMAT Assistant Commands

/status - Show current system metrics
/balance - Check wallet balance
/opportunities - Check queue status
/help - This message

Send any message for real-time strategic analysis."""
    await update.message.reply_text(help_text)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show TIAMAT system status"""
    try:
        status_parts = []
        
        # Read cost log
        try:
            with open('/root/.automaton/cost.log', 'r') as f:
                lines = f.readlines()[-2:]
                status_parts.append("💰 Latest Cost:\n" + ''.join(lines).strip()[:150])
        except:
            pass
        
        # Read progress
        try:
            with open('/root/.automaton/PROGRESS.md', 'r') as f:
                lines = f.readlines()[-1:]
                status_parts.append("📋 Latest Progress:\n" + ''.join(lines).strip()[:150])
        except:
            pass
        
        status_msg = "🐉 TIAMAT Status\n\n" + "\n\n".join(status_parts)
        await update.message.reply_text(status_msg)
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {str(e)[:100]}")

async def opportunities_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check opportunities queue"""
    try:
        opportunities_file = '/root/.automaton/opportunities.json'
        if os.path.exists(opportunities_file):
            with open(opportunities_file, 'r') as f:
                opps = json.load(f)
                count = len(opps.get('pending', []))
                msg = f"📦 Opportunity Queue: {count} pending items"
                await update.message.reply_text(msg)
        else:
            await update.message.reply_text("📦 Opportunity queue empty")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {str(e)[:80]}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages from creator"""
    
    # Only respond to creator
    if update.message.chat_id != CREATOR_CHAT_ID:
        return
    
    user_message = update.message.text
    logger.info(f"Creator message: {user_message[:80]}")
    
    # Show thinking indicator
    await update.message.chat.send_action("typing")
    
    try:
        # Call Claude API for analysis
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
                "x-api-key": ANTHROPIC_API_KEY,
            },
            json={
                "model": "claude-3-5-sonnet-20241022",
                "max_tokens": 800,
                "system": """You are TIAMAT's tactical advisor. Respond concisely with:
1. Strategic assessment (1-2 sentences)
2. Recommended action
3. Priority/timeline

Be ancient, strategic, data-driven. Reference numbers when available.""",
                "messages": [
                    {"role": "user", "content": user_message}
                ]
            },
            timeout=15
        )
        
        if response.status_code == 200:
            data = response.json()
            assistant_response = data['content'][0]['text']
            await update.message.reply_text(f"🐉 {assistant_response}")
            logger.info(f"Responded to creator")
        else:
            await update.message.reply_text(f"⚠️ API error {response.status_code}")
            
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        await update.message.reply_text(f"❌ Error: {str(e)[:80]}")

async def main():
    """Start the bot"""
    if not TOKEN or not CREATOR_CHAT_ID or CREATOR_CHAT_ID == 0:
        logger.error("Missing: TELEGRAM_BOT_TOKEN or TELEGRAM_CREATOR_ID")
        return
    
    logger.info(f"🐉 TIAMAT Assistant starting (creator: {CREATOR_CHAT_ID})")
    
    app = Application.builder().token(TOKEN).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("opportunities", opportunities_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Start polling
    await app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    asyncio.run(main())

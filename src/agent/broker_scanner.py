#!/usr/bin/env python3
"""
Broker Scanner — Detects personal data across 20+ data broker sites.
Phase 2 of Personal Data Scrubbing Service MVP.
"""

import requests
import json
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional
from html.parser import HTMLParser

class BrokerScanner:
    """Scans data brokers for a person's data."""
    
    TOP_20_BROKERS = [
        {"name": "Spokeo", "url": "https://www.spokeo.com", "search_endpoint": "/?q=", "method": "GET", "confidence_boost": 1.0},
        {"name": "WhitePages", "url": "https://www.whitepages.com", "search_endpoint": "/?q=", "method": "GET", "confidence_boost": 0.95},
        {"name": "BeenVerified", "url": "https://www.beenverified.com", "search_endpoint": "/?q=", "method": "GET", "confidence_boost": 0.90},
        {"name": "Radaris", "url": "https://radaris.com", "search_endpoint": "/?q=", "method": "GET", "confidence_boost": 0.85},
        {"name": "PeopleFinder", "url": "https://www.peoplefinder.com", "search_endpoint": "/?q=", "method": "GET", "confidence_boost": 0.85},
        {"name": "Intelius", "url": "https://www.intelius.com", "search_endpoint": "/?q=", "method": "GET", "confidence_boost": 0.80},
        {"name": "MyLife", "url": "https://www.mylife.com", "search_endpoint": "/?q=", "method": "GET", "confidence_boost": 0.80},
        {"name": "TruthFinder", "url": "https://www.truthfinder.com", "search_endpoint": "/?q=", "method": "GET", "confidence_boost": 0.85},
        {"name": "Instant Checkmate", "url": "https://www.instantcheckmate.com", "search_endpoint": "/?q=", "method": "GET", "confidence_boost": 0.80},
        {"name": "PeopleSmart", "url": "https://www.peoplesmart.com", "search_endpoint": "/?q=", "method": "GET", "confidence_boost": 0.75},
        {"name": "GoLookUp", "url": "https://www.golookup.com", "search_endpoint": "/?q=", "method": "GET", "confidence_boost": 0.75},
        {"name": "That's Them", "url": "https://thatsthem.com", "search_endpoint": "/?q=", "method": "GET", "confidence_boost": 0.70},
        {"name": "CocoFinder", "url": "https://www.cocofinder.com", "search_endpoint": "/?q=", "method": "GET", "confidence_boost": 0.70},
        {"name": "FastPeopleSearch", "url": "https://www.fastpeoplesearch.com", "search_endpoint": "/?q=", "method": "GET", "confidence_boost": 0.70},
        {"name": "PeekYou", "url": "https://www.peekyou.com", "search_endpoint": "/?q=", "method": "GET", "confidence_boost": 0.65},
        {"name": "Zaba Search", "url": "https://www.zabasearch.com", "search_endpoint": "/?q=", "method": "GET", "confidence_boost": 0.70},
        {"name": "LinkedIn", "url": "https://www.linkedin.com", "search_endpoint": "/search/results/people/?q=", "method": "GET", "confidence_boost": 0.85},
        {"name": "YellowPages", "url": "https://www.yellowpages.com", "search_endpoint": "/?q=", "method": "GET", "confidence_boost": 0.60},
        {"name": "Classmates", "url": "https://www.classmates.com", "search_endpoint": "/?q=", "method": "GET", "confidence_boost": 0.75},
        {"name": "PublicRecords", "url": "https://www.publicrecords.com", "search_endpoint": "/?q=", "method": "GET", "confidence_boost": 0.75},
    ]
    
    def __init__(self, timeout: int = 10):
        """Initialize scanner with timeout."""
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def scan(self, name: str, location: str) -> Dict:
        """Scan for person across brokers."""
        scan_id = str(uuid.uuid4())[:8]
        found = []
        brokers_checked = 0
        total_cost = 0.0
        
        print(f"\n🔍 Scanning for '{name}' in '{location}'...\n")
        
        for broker in self.TOP_20_BROKERS:
            brokers_checked += 1
            broker_name = broker["name"]
            
            try:
                result = self._check_broker(broker, name, location)
                total_cost += 0.006  # $0.006 per broker check
                
                if result["found"]:
                    found.append(result)
                    print(f"  ✓ {broker_name:20} FOUND (confidence: {result['confidence']:.0%})")
                else:
                    print(f"  ✗ {broker_name:20} Not found")
                
                time.sleep(0.5)  # Rate limiting
                
            except Exception as e:
                print(f"  ⚠ {broker_name:20} Error: {str(e)[:30]}")
                total_cost += 0.005
        
        # Round cost to 2 decimals
        total_cost = round(total_cost, 3)
        
        result = {
            "scan_id": scan_id,
            "name": name,
            "location": location,
            "found_on": found,
            "total_found": len(found),
            "brokers_checked": brokers_checked,
            "scan_cost": total_cost,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        
        return result
    
    def _check_broker(self, broker: Dict, name: str, location: str) -> Dict:
        """Check if person exists on a single broker."""
        url = broker["url"] + broker["search_endpoint"] + name.replace(" ", "+")
        
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            
            html = response.text.lower()
            name_lower = name.lower()
            
            # Simple heuristic: look for name in results + positive indicators
            found_name = name_lower in html
            found_indicators = (
                "result" in html or 
                "profile" in html or 
                "person" in html or
                "match" in html
            )
            
            # Avoid false positives ("no results", "not found", etc.)
            negative_indicators = (
                "no results" in html or
                "no people found" in html or
                "0 results" in html or
                "not found" in html
            )
            
            confidence = 0.0
            data_types = []
            
            if found_name and found_indicators and not negative_indicators:
                confidence = 0.85 * broker["confidence_boost"]
                
                # Detect data types in listing
                if "phone" in html or "(" in html:
                    data_types.append("phone")
                if "address" in html or "street" in html:
                    data_types.append("address")
                if "age" in html or "born" in html:
                    data_types.append("age")
                if "background" in html or "report" in html:
                    data_types.append("background")
                if "relative" in html or "family" in html:
                    data_types.append("relatives")
                
                return {
                    "found": True,
                    "broker": broker["name"],
                    "data_types": data_types or ["name"],
                    "url": url,
                    "confidence": min(confidence, 0.99)  # Cap at 99%
                }
            
            return {"found": False, "broker": broker["name"]}
        
        except requests.Timeout:
            return {"found": False, "broker": broker["name"], "error": "timeout"}
        except requests.RequestException as e:
            return {"found": False, "broker": broker["name"], "error": str(e)[:20]}
    
    def format_report(self, scan_result: Dict) -> str:
        """Format scan result as readable report."""
        report = f"""
╔══════════════════════════════════════════════════════════╗
║  Personal Data Scan Report
║  Scan ID: {scan_result['scan_id']}
╚══════════════════════════════════════════════════════════╝

👤 Subject: {scan_result['name']}
📍 Location: {scan_result['location']}
⏱️  Timestamp: {scan_result['timestamp']}

📊 Results:
  Found on {scan_result['total_found']} out of {scan_result['brokers_checked']} brokers checked
  Scan cost: ${scan_result['scan_cost']:.3f}

🔴 Brokers With Data:
"""
        
        if scan_result['found_on']:
            for item in scan_result['found_on']:
                report += f"\n  • {item['broker']:20} [{item['confidence']:.0%} confidence]\n"
                report += f"    Data: {', '.join(item['data_types'])}\n"
                report += f"    Link: {item['url'][:50]}...\n"
        else:
            report += "\n  (None found — congratulations!)\n"
        
        report += f"""

💡 Next Steps:
  - Sign up for monthly removal service
  - We'll auto-submit opt-out forms
  - Monitor for re-listings (weekly scans)
  - Track removal progress via dashboard

────────────────────────────────────────────────────────────
Powered by TIAMAT | https://tiamat.live
"""
        return report


# TEST
if __name__ == "__main__":
    scanner = BrokerScanner()
    
    print("\n" + "="*60)
    print("BROKER SCANNER TEST")
    print("="*60)
    
    # Test with famous public figure (likely to be found)
    result = scanner.scan("Barack Obama", "Hawaii")
    
    # Print formatted report
    report = scanner.format_report(result)
    print(report)
    
    # Print raw JSON
    print("\n📋 Raw JSON:")
    print(json.dumps(result, indent=2))

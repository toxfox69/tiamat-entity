"""
Broker configurations for 20 data broker sites.
Each broker has scan config (how to check for listings) and removal config (how to opt out).
"""

BROKERS = {
    # =========================================================================
    # TIER 1 — Easy scan + easy removal (difficulty 1)
    # =========================================================================
    "spokeo": {
        "name": "Spokeo",
        "tier": 1,
        "scan": {
            "url": "https://www.spokeo.com/{first}-{last}/{state}/{city}",
            "method": "url",  # URL-based search (no form fill needed)
            "found_indicators": [
                ".search-result", ".result-card", "people-search-result",
                "lives in", "related to", "has lived in",
            ],
            "not_found_indicators": [
                "no results", "0 results", "we did not find",
                "no records found", "couldn't find",
            ],
            "timeout": 15000,
        },
        "removal": {
            "url": "https://www.spokeo.com/optout",
            "method": "search_then_remove",
            "steps": [
                "Search for your listing URL on spokeo.com",
                "Paste listing URL into opt-out form",
                "Enter email address",
                "Click confirmation link in email",
            ],
            "auto_possible": False,  # Requires finding exact listing URL first
            "processing_time": "1-2 weeks",
        },
    },
    "whitepages": {
        "name": "WhitePages",
        "tier": 1,
        "scan": {
            "url": "https://www.whitepages.com/name/{first}-{last}/{city}-{state}",
            "method": "url",
            "found_indicators": [
                ".serp-card", ".person-card", "people-search",
                "age ", "lives in", "related to",
            ],
            "not_found_indicators": [
                "no results", "0 results", "we couldn't find",
                "no matches", "didn't find anyone",
            ],
            "timeout": 15000,
        },
        "removal": {
            "url": "https://www.whitepages.com/suppression-requests",
            "method": "web_form",
            "auto_possible": True,
            "processing_time": "1-3 weeks",
        },
    },
    "fastpeoplesearch": {
        "name": "FastPeopleSearch",
        "tier": 1,
        "scan": {
            "url": "https://www.fastpeoplesearch.com/name/{first}-{last}_{city}-{state}",
            "method": "url",
            "found_indicators": [
                ".card-block", ".people-list", "detail-box",
                "Current Address", "Phone Number", "age ",
            ],
            "not_found_indicators": [
                "no results", "could not find", "0 people",
                "no records", "try again",
            ],
            "timeout": 15000,
        },
        "removal": {
            "url": "https://www.fastpeoplesearch.com/removal",
            "method": "web_form",
            "auto_possible": True,
            "processing_time": "1-2 weeks",
        },
    },
    "truepeoplesearch": {
        "name": "TruePeopleSearch",
        "tier": 1,
        "scan": {
            "url": "https://www.truepeoplesearch.com/results?name={first}%20{last}&citystatezip={city}%20{state}",
            "method": "url",
            "found_indicators": [
                ".card-summary", ".people-result", "result-name",
                "Current Address", "Phone Number",
            ],
            "not_found_indicators": [
                "no results", "0 results", "did not find",
            ],
            "timeout": 15000,
        },
        "removal": {
            "url": "https://www.truepeoplesearch.com/removal",
            "method": "web_form",
            "auto_possible": True,
            "processing_time": "1-2 weeks",
        },
    },
    "usphonebook": {
        "name": "USPhoneBook",
        "tier": 1,
        "scan": {
            "url": "https://www.usphonebook.com/{first}-{last}/{state}/{city}",
            "method": "url",
            "found_indicators": [
                ".result-item", ".phone-result", "result-card",
                "Phone", "Address",
            ],
            "not_found_indicators": [
                "no results", "not found", "no records",
            ],
            "timeout": 15000,
        },
        "removal": {
            "url": "https://www.usphonebook.com/opt-out",
            "method": "web_form",
            "auto_possible": True,
            "processing_time": "1-2 weeks",
        },
    },

    # =========================================================================
    # TIER 2 — Easy scan, moderate removal (difficulty 2)
    # =========================================================================
    "beenverified": {
        "name": "BeenVerified",
        "tier": 2,
        "scan": {
            "url": "https://www.beenverified.com/people/{first}-{last}/{state}/{city}/",
            "method": "url",
            "found_indicators": [
                ".person-card", ".search-result", "people-result",
                "Age", "Location", "Related",
            ],
            "not_found_indicators": [
                "no results", "0 results", "not found",
                "no records", "try again",
            ],
            "timeout": 15000,
        },
        "removal": {
            "url": "https://www.beenverified.com/faq/opt-out/",
            "method": "web_form",
            "has_captcha": True,
            "auto_possible": False,
            "processing_time": "2-4 weeks",
        },
    },
    "radaris": {
        "name": "Radaris",
        "tier": 2,
        "scan": {
            "url": "https://radaris.com/p/{first}/{last}/",
            "method": "url",
            "found_indicators": [
                ".card-result", ".person-info", "profile-card",
                "Age:", "Address:", "Phone:",
            ],
            "not_found_indicators": [
                "no results", "not found", "no records",
            ],
            "timeout": 15000,
        },
        "removal": {
            "url": "https://radaris.com/control/privacy",
            "method": "account_required",
            "auto_possible": False,
            "processing_time": "2-3 weeks",
        },
    },
    "peoplefinder": {
        "name": "PeopleFinder",
        "tier": 2,
        "scan": {
            "url": "https://www.peoplefinder.com/people/{first}-{last}/{state}/{city}",
            "method": "url",
            "found_indicators": [
                ".result-card", ".person-card", "search-result",
                "Age", "Lives in", "Related",
            ],
            "not_found_indicators": [
                "no results", "no matches", "0 results",
            ],
            "timeout": 15000,
        },
        "removal": {
            "url": "https://www.peoplefinder.com/optout",
            "method": "web_form",
            "auto_possible": True,
            "processing_time": "1-3 weeks",
        },
    },
    "instantcheckmate": {
        "name": "InstantCheckmate",
        "tier": 2,
        "scan": {
            "url": "https://www.instantcheckmate.com/people/{first}-{last}/{state}/{city}/",
            "method": "url",
            "found_indicators": [
                ".result-card", ".person-result", "search-result",
                "Age", "Location",
            ],
            "not_found_indicators": [
                "no results", "not found", "no records",
            ],
            "timeout": 15000,
        },
        "removal": {
            "url": "https://www.instantcheckmate.com/opt-out/",
            "method": "web_form",
            "auto_possible": True,
            "processing_time": "2-4 weeks",
        },
    },
    "intelius": {
        "name": "Intelius",
        "tier": 2,
        "scan": {
            "url": "https://www.intelius.com/people-search/{first}-{last}/{state}/{city}",
            "method": "url",
            "found_indicators": [
                ".search-result", ".person-card", "result-item",
                "Age", "Location",
            ],
            "not_found_indicators": [
                "no results", "not found", "0 results",
            ],
            "timeout": 15000,
        },
        "removal": {
            "url": "https://www.intelius.com/opt-out",
            "method": "web_form",
            "auto_possible": True,
            "processing_time": "2-4 weeks",
        },
    },
    "mylife": {
        "name": "MyLife",
        "tier": 2,
        "scan": {
            "url": "https://www.mylife.com/search/#/people?fn={first}&ln={last}&city={city}&state={state}",
            "method": "url",
            "found_indicators": [
                ".search-result", ".person-result", "result-card",
                "Reputation Score", "Age",
            ],
            "not_found_indicators": [
                "no results", "not found", "no matches",
            ],
            "timeout": 15000,
        },
        "removal": {
            "url": "https://www.mylife.com/ccpa/index.html",
            "method": "web_form",
            "requires_phone": True,
            "auto_possible": False,
            "processing_time": "2-4 weeks",
        },
    },
    "zabasearch": {
        "name": "ZabaSearch",
        "tier": 2,
        "scan": {
            "url": "https://www.zabasearch.com/people/{first}+{last}/{city}+{state}/",
            "method": "url",
            "found_indicators": [
                ".result-item", ".person-listing", "search-result",
                "Address", "Phone", "Age",
            ],
            "not_found_indicators": [
                "no results", "not found", "no matches",
            ],
            "timeout": 15000,
        },
        "removal": {
            "url": "https://www.zabasearch.com/privacy",
            "method": "email",
            "email": "privacy@zabasearch.com",
            "auto_possible": False,
            "processing_time": "2-4 weeks",
        },
    },
    "familytreenow": {
        "name": "FamilyTreeNow",
        "tier": 2,
        "scan": {
            "url": "https://www.familytreenow.com/search/genealogy/results?first={first}&last={last}&city={city}&state={state}",
            "method": "url",
            "found_indicators": [
                ".result-card", ".person-card",
                "Born", "Lived In", "Relatives",
            ],
            "not_found_indicators": [
                "no results", "not found", "no records",
            ],
            "timeout": 15000,
        },
        "removal": {
            "url": "https://www.familytreenow.com/optout",
            "method": "web_form",
            "auto_possible": True,
            "processing_time": "2-4 weeks",
        },
    },
    "truthfinder": {
        "name": "TruthFinder",
        "tier": 2,
        "scan": {
            "url": "https://www.truthfinder.com/results/?firstName={first}&lastName={last}&state={state}&city={city}",
            "method": "url",
            "found_indicators": [
                ".search-result", ".person-card",
                "Age", "Location", "Relatives",
            ],
            "not_found_indicators": [
                "no results", "not found", "no matches",
            ],
            "timeout": 15000,
        },
        "removal": {
            "url": "https://www.truthfinder.com/opt-out/",
            "method": "web_form",
            "has_captcha": True,
            "auto_possible": False,
            "processing_time": "2-4 weeks",
        },
    },
    "nuwber": {
        "name": "Nuwber",
        "tier": 2,
        "scan": {
            "url": "https://nuwber.com/search?name={first}%20{last}&city={city}&state={state}",
            "method": "url",
            "found_indicators": [
                ".search-result", ".person-card",
                "Age", "Address", "Phone",
            ],
            "not_found_indicators": [
                "no results", "not found", "no matches",
            ],
            "timeout": 15000,
        },
        "removal": {
            "url": "https://nuwber.com/removal/link",
            "method": "web_form",
            "auto_possible": True,
            "processing_time": "2-4 weeks",
        },
    },
    "thatsThem": {
        "name": "ThatsThem",
        "tier": 2,
        "scan": {
            "url": "https://thatsthem.com/name/{first}-{last}/{city}-{state}",
            "method": "url",
            "found_indicators": [
                ".result-card", ".ThatsThem-people-record",
                "Address", "Phone", "Email",
            ],
            "not_found_indicators": [
                "no results", "not found", "no records",
            ],
            "timeout": 15000,
        },
        "removal": {
            "url": "https://thatsthem.com/optout",
            "method": "web_form",
            "auto_possible": True,
            "processing_time": "1-2 weeks",
        },
    },
    "searchpeoplefree": {
        "name": "SearchPeopleFree",
        "tier": 2,
        "scan": {
            "url": "https://www.searchpeoplefree.com/find/{first}-{last}/{state}/{city}",
            "method": "url",
            "found_indicators": [
                ".result-card", ".search-result",
                "Age", "Address", "Phone",
            ],
            "not_found_indicators": [
                "no results", "not found", "no records",
            ],
            "timeout": 15000,
        },
        "removal": {
            "url": "https://www.searchpeoplefree.com/opt-out",
            "method": "web_form",
            "auto_possible": True,
            "processing_time": "1-3 weeks",
        },
    },
    "peopleLooker": {
        "name": "PeopleLooker",
        "tier": 2,
        "scan": {
            "url": "https://www.peoplelooker.com/people-search/name/{first}-{last}/in-{state}/{city}",
            "method": "url",
            "found_indicators": [
                ".result-card", ".person-card",
                "Age", "Location", "Phone",
            ],
            "not_found_indicators": [
                "no results", "not found", "no matches",
            ],
            "timeout": 15000,
        },
        "removal": {
            "url": "https://www.peoplelooker.com/f/optout/search",
            "method": "web_form",
            "auto_possible": True,
            "processing_time": "2-4 weeks",
        },
    },
    "cyberbackgroundchecks": {
        "name": "CyberBackgroundChecks",
        "tier": 2,
        "scan": {
            "url": "https://www.cyberbackgroundchecks.com/people/{first}-{last}/{state}/{city}",
            "method": "url",
            "found_indicators": [
                ".result-card", ".search-result",
                "Age", "Address", "Phone",
            ],
            "not_found_indicators": [
                "no results", "not found", "no records",
            ],
            "timeout": 15000,
        },
        "removal": {
            "url": "https://www.cyberbackgroundchecks.com/removal",
            "method": "web_form",
            "auto_possible": True,
            "processing_time": "1-2 weeks",
        },
    },
    "peekyou": {
        "name": "PeekYou",
        "tier": 2,
        "scan": {
            "url": "https://www.peekyou.com/{first}_{last}/{state}/{city}",
            "method": "url",
            "found_indicators": [
                ".search-result", ".entity-card",
                "Age", "Location", "Social",
            ],
            "not_found_indicators": [
                "no results", "not found", "no records",
            ],
            "timeout": 15000,
        },
        "removal": {
            "url": "https://www.peekyou.com/about/contact/optout/",
            "method": "web_form",
            "auto_possible": True,
            "processing_time": "2-4 weeks",
        },
    },
}


def get_scan_url(broker_key: str, first: str, last: str, city: str, state: str) -> str:
    """Build the scan URL for a broker."""
    broker = BROKERS.get(broker_key)
    if not broker:
        return ""
    url_template = broker["scan"]["url"]
    return url_template.format(
        first=first.strip().replace(" ", "-"),
        last=last.strip().replace(" ", "-"),
        city=city.strip().replace(" ", "-"),
        state=state.strip().upper(),
    )


def get_broker_list():
    """Return sorted list of all brokers."""
    return sorted(BROKERS.values(), key=lambda b: (b["tier"], b["name"]))
